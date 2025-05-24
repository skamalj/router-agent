import json
import os
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph_dynamodb_checkpoint import DynamoDBSaver
from langgraph_reducer import PrunableStateFactory
from langgraph_utils import call_model
from logger import get_logger
import boto3

logger = get_logger(__name__)

model_name = os.getenv("MODEL_NAME")
provider_name = os.getenv("PROVIDER_NAME")
stepfunctions_client = boto3.client("stepfunctions")

# Supervisor model invocation
def call_gw_model(state): 
    with open("agent_prompt.txt", "r", encoding="utf-8") as file:
        system_message = file.read()
    messages = state["messages"]
    system_msg = SystemMessage(content=system_message)

    logger.debug("Total messages received: %d", len(messages))
    logger.debug("Messages: %s", messages)

    for i, msg in enumerate(messages):
        if isinstance(msg, SystemMessage):
            logger.debug("System message found at index %d", i)

    if isinstance(messages[0], SystemMessage):
        messages[0] = system_msg
    else:
        messages.insert(0, system_msg)

    logger.debug("Messages after prepending system message: %d", len(messages))

    response = call_model(model_name, provider_name, messages)
    logger.debug("Response from model: %s", response)

    return {"messages": [response]}


def init_graph():
    with DynamoDBSaver.from_conn_info(
        table_name="whatsapp_checkpoint",
        max_write_request_units=100,
        max_read_request_units=100,
        ttl_seconds=86400
    ) as saver:
        graph = StateGraph(PrunableMessagesState)
        graph.add_node("agent", call_gw_model)
        graph.add_edge(START, "agent")
        graph.add_edge("agent", END)
        return graph.compile(checkpointer=saver)


# Message history retention thresholds
min_messages = int(os.getenv("MSG_HISTORY_TO_KEEP", 20))
max_messages = int(os.getenv("DELETE_TRIGGER_COUNT", 30))
PrunableMessagesState = PrunableStateFactory.create_prunable_state(min_messages, max_messages)
app = init_graph()

# DynamoDB setup
dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
table = dynamodb.Table("UserProfiles")

def get_profile_id(userid):
    try:
        response = table.query(
            IndexName="UserIdIndex",
            KeyConditionExpression="userid = :uid",
            ExpressionAttributeValues={":uid": userid}
        )
        items = response.get("Items", [])
        return items[0]["profile_id"] if items else None
    except Exception as e:
        logger.error("Failed to fetch profile_id for user %s: %s", userid, str(e))
        return None

def get_all_userids_and_channels(profile_id):
    try:
        response = table.query(
            KeyConditionExpression="profile_id = :pid",
            ExpressionAttributeValues={":pid": profile_id}
        )
        items = response.get("Items", [])
        return [(item["userid"], item["channel"]) for item in items]
    except Exception as e:
        logger.error("Failed to fetch userids/channels for profile %s: %s", profile_id, str(e))
        return []

def lambda_handler(event, context):
    for record in event["Records"]:
        try:
            body = json.loads(record["body"])
        except Exception as e:
            logger.error("Failed to parse message body: %s", str(e))
            continue

        channel_type = body.get("channel_type")
        recipient = body.get("from")
        message = body.get("messages")

        if not all([channel_type, recipient, message]):
            logger.warning("Skipping message due to missing fields: %s", body)
            continue

        profile_id = get_profile_id(recipient)
        if not profile_id:
            logger.info("No profile found for user: %s. Skipping.", recipient)
            continue

        user_profiles = get_all_userids_and_channels(profile_id)
        profile_info = "\n".join([f"- UserID: {uid}, Channel: {ch}" for uid, ch in user_profiles])
        logger.debug("User Profiles for %s:\n%s", recipient, profile_info)

        input_message = {"messages": [HumanMessage(message)]}
        config = {"configurable": {"thread_id": profile_id}}

        try:
            response = app.invoke(input_message, config)
            nextagent_raw = response["messages"][-1].content
            logger.debug("Raw agent response: %s", nextagent_raw)

            nextagent = json.loads(nextagent_raw).get("agent_name", "awsagent")
            result = {
                "fromagent": "router-agent",
                "nextagent": nextagent,
                "message": message,
                "thread_id": profile_id,
                "channel_type": channel_type,
                "from": recipient
            }
            logger.info("Routing to next agent: %s", nextagent)

            stepfunctions_client.start_execution(
                stateMachineArn=os.getenv("STEP_FUNCTION_ARN"),
                input=json.dumps(result)
            )
            logger.info("Successfully started Step Function execution.")

        except Exception as e:
            logger.error("Error processing record for user %s: %s", recipient, str(e))

    return {"statusCode": 200, "body": "Processed messages"}
