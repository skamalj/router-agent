# 🧠 Router Agent Lambda (LangGraph + AWS)

This AWS Lambda function routes incoming user messages to the appropriate next agent using [LangGraph](https://github.com/langchain-ai/langgraph), with:

- **SQS trigger**
- **Secrets Manager integration**
- **DynamoDB for user profile + state**
- **Step Functions for orchestration**
- **Configurable environment variables**
- **CI/CD with GitHub Actions**

---

## 🚀 Functionality

1. **Triggered via SQS** (`UnifiedChannelQueue`)
2. Retrieves user's `profile_id` from **DynamoDB**
3. Resolves all user IDs and channels linked to the profile
4. Passes state to a LangGraph-based model (`call_model()`)
5. Triggers a **Step Function** (`AgentStepFunction`) for the next agent
6. Structured logs sent to **CloudWatch**

---


## 📜 SAM Template Overview

The Lambda function is deployed via AWS SAM using:

- **SQS Trigger** (`UnifiedChannelQueue`)
- **DLQ** (`RouterDeadLetterQueue`) with retry policy
- **Secrets Manager** for API Gateway auth
- IAM permissions for DynamoDB, Step Functions, and SQS

See `template.yaml` for full configuration.

---

## 🔧 Environment Variables

These variables are configured in the `template.yaml`:

| Variable               | Description |
|------------------------|-------------|
| `MODEL_NAME`           | Name of the model (e.g., `gpt-4o`) |
| `PROVIDER_NAME`        | LLM provider (e.g., `openai`) |
| `MSG_HISTORY_TO_KEEP`  | How many past messages to retain in memory (default: 20) |
| `DELETE_TRIGGER_COUNT` | Number of messages before pruning state (default: 30) |
| `STEP_FUNCTION_ARN`    | ARN of the Step Function to invoke |
| `ROUTER_QUEUE_URL`     | URL of the SQS queue (RouterQueue) |
| `API_GW_URL`           | Resolved from AWS Secrets Manager |
| `API_GW_KEY`           | Resolved from AWS Secrets Manager |
| `LOG_LEVEL`            | Logging level (`debug`, `info`, `warning`, etc.) |

---

## 🔐 Secrets Manager Integration

Secrets are dynamically resolved at runtime:

- `API_GW_URL` → `{{resolve:secretsmanager:<ApiGWEndpoint>}}`
- `API_GW_KEY` → `{{resolve:secretsmanager:<ApiGWKey>}}`

Ensure these secrets are created in Secrets Manager before deployment.

---

## 🪵 Logging

Set the log level with:

```bash
export LOG_LEVEL=debug
```

Logs are printed with timestamps and appear in **CloudWatch Logs**.

---

## 🧪 Sample SQS Message

```json
{
  "channel_type": "whatsapp",
  "from": "user123",
  "messages": "What's the status of my policy?"
}
```

---

## ✅ Example Output to Step Function

```json
{
  "fromagent": "router-agent",
  "nextagent": "awsagent",
  "message": "What's the status of my policy?",
  "thread_id": "profile-xyz",
  "channel_type": "whatsapp",
  "from": "user123"
}
```

---

## 📤 Queues

| Queue                  | Description |
|------------------------|-------------|
| `UnifiedChannelQueue` | Incoming messages (trigger Lambda) |
| `RouterQueue`         | Used internally by router logic |
| `RouterDeadLetterQueue` | DLQ for failed messages (14-day retention) |

---

## 🔐 Permissions Required

The Lambda function has permission to:

- Start and describe executions in **Step Functions**
- Read/write to **DynamoDB** tables (full access)
- Read from **Secrets Manager**
- Send/receive/delete from **SQS**

---

## 📦 GitHub Actions (CI/CD)

This project includes a GitHub Actions pipeline for automatic deployment to AWS on every push to the `main` branch.

**Workflow location:** `.github/workflows/deploy.yml`

```yaml
on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: dev
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v3
      - uses: aws-actions/setup-sam@v2
      - uses: aws-actions/configure-aws-credentials@v1
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-2
      - run: sam build --use-container
      - run: sam deploy --no-confirm-changeset --no-fail-on-empty-changeset
```

Make sure to set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in your GitHub repository secrets.

---

## 👥 Authors

Built by the @Kamal

---

## 📄 License

MIT License (or insert applicable license)
