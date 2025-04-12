import json
import os
from langgraph.graph import StateGraph,  START, END
from langchain_core.messages import SystemMessage,  HumanMessage
from langgraph_dynamodb_checkpoint import DynamoDBSaver
from langgraph_reducer import PrunableStateFactory
from langgraph_utils import call_model
import boto3

model_name = model=os.getenv("MODEL_NAME")
provider_name = os.getenv("PROVIDER_NAME")
stepfunctions_client = boto3.client("stepfunctions")

# Function to call the supervisor model
def call_gw_model(state): 
    with open("agent_prompt.txt", "r", encoding="utf-8") as file:
        system_message = file.read()
        messages = state["messages"]
        system_msg = SystemMessage(content=system_message)

        if isinstance(messages[0], SystemMessage):
            messages[0]=system_msg
        else:
            messages.insert(0, system_msg)

        response = call_model(model_name, provider_name, messages)
        
        return {"messages": [response]}

def init_graph():
    with DynamoDBSaver.from_conn_info(table_name="whatsapp_checkpoint", max_write_request_units=100,max_read_request_units=100, ttl_seconds=86400) as saver:
        graph = StateGraph(PrunableMessagesState)
        
        graph.add_node("agent", call_gw_model)
    
        graph.add_edge(START, "agent")
        graph.add_edge("agent", END)
       
        app = graph.compile(checkpointer=saver)
        return app

min_number_of_messages_to_keep = int(os.environ.get("MSG_HISTORY_TO_KEEP", 20))
max_number_of_messages_to_keep = int(os.environ.get("DELETE_TRIGGER_COUNT", 30))    
PrunableMessagesState = PrunableStateFactory.create_prunable_state(min_number_of_messages_to_keep, max_number_of_messages_to_keep)   

app = init_graph()

# Initialize AWS resources
dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")  # Change region if needed
table = dynamodb.Table("UserProfiles")

def get_profile_id(userid):
    """Fetch profile_id from DynamoDB using GSI on userid."""
    response = table.query(
        IndexName="UserIdIndex",
        KeyConditionExpression="userid = :uid",
        ExpressionAttributeValues={":uid": userid}
    )
    items = response.get("Items", [])
    return items[0]["profile_id"] if items else None

def get_all_userids_and_channels(profile_id):
    """Fetch all userids and channels associated with the profile_id."""
    response = table.query(
        KeyConditionExpression="profile_id = :pid",
        ExpressionAttributeValues={":pid": profile_id}
    )
    items = response.get("Items", [])
    return [(item["userid"], item["channel"]) for item in items]

def lambda_handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])  # SQS message body

        # Extract required fields
        channel_type = body.get("channel_type")  # WhatsApp, Email, etc.
        recipient = body.get("from")  # User ID (userid)
        message = body.get("messages")  # User's query

        # Validate required fields
        if not all([channel_type, recipient, message]):
            print("Skipping message due to missing fields")
            continue  # Skip this record

        # Step 1: Get profile_id for this user
        profile_id = get_profile_id(recipient)
        if not profile_id:
            print(f"No profile found for user: {recipient}, skipping.")
            continue

        # Step 2: Get all associated userids & channels
        user_profiles = get_all_userids_and_channels(profile_id)

        # Format profiles for the prompt
        profile_info = "\n".join(
            [f"- UserID: {uid}, Channel: {ch}" for uid, ch in user_profiles]
        )

        print(f"User Profiles for {recipient}: \n{profile_info}")

        input_message = {
            "messages": [HumanMessage(message)],
        }

        config = {"configurable": {"thread_id": profile_id}}
        nextagent = app.invoke(input_message, config)
        print(f"Next agent: {nextagent}")
        response = {
            "nextagent": nextagent,
            "message": message,
            "thread_id": profile_id,
            "channel_type": channel_type,
            "from": recipient
        }

        print("Response:", response)

        try:
            stepfunctions_client.start_execution(
                stateMachineArn=os.getenv("STEP_FUNCTION_ARN"),
                input=json.dumps(response)
            )
            print("Successfully started Step Function execution.")
        except Exception as e:
            print("Failed to start Step Function execution:", str(e))

    return
