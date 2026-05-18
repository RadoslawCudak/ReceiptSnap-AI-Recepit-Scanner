# Serverless AI Receipt Scanner & Categorizer 🧾🤖

A serverless Python Function App that automates the process of extracting, normalizing, and categorizing data from retail receipts. The system leverages state-of-the-art Cloud AI services from Microsoft Azure (**Azure AI Document Intelligence** and **Azure OpenAI GPT-4o**) to convert unstructured receipt images into highly structured, clean NoSQL database records.

This backend component is fully automated using a robust **CI/CD pipeline with GitHub Actions and RBAC (Role-Based Access Control) authentication**, ensuring production-grade deployment standards.

---

## 🏗️ Architecture & Cloud Services

The project uses an **Event-Driven, Serverless Architecture** built entirely on the Microsoft Azure ecosystem:

1. **Azure Static Web Apps**: Hosts the modern frontend application and handles secure **GitHub Authentication (OAuth 2.0)** for users.
2. **Azure Blob Storage**: Acts as the entry point. Uploading a receipt image to the path `receipts/{username}/{filename}` triggers the entire backend pipeline.
3. **Azure Functions (Function App)**: The serverless orchestrator written in Python. It executes on-demand, processes the file stream, and communicates with AI models.
4. **Azure AI Document Intelligence (Form Recognizer)**: Utilizes the `prebuilt-receipt` model to perform advanced OCR, extracting fields like merchant name, total amounts, dates, and itemized lines.
5. **Azure OpenAI Service (GPT-4o)**:
   - **Entity Normalization**: Standardizes chaotic merchant names (e.g., clearing legal suffixes like `Sp. z o.o.`, tax numbers, and store IDs into a clean `"Lidl"` or `"Biedronka"`).
   - **Semantic Classification**: Maps raw, shortened cash-register product names (e.g., `"MLEK.UHT.3,2%"`) into strict, pre-defined expense categories.
6. **Azure Table Storage**: A high-performance NoSQL key-value store that saves structured data split into `Summary` records and relational `Product` items.

---

## 🛠️ Data Structure in Table Storage

The application saves two types of entities under the same table (`ReceiptsData`) to enable fast relational-like queries without the overhead of an SQL server:

### 1. Receipt Summary Entity (`Type: "Summary"`)
- **PartitionKey**: `{username}_Summary`
- **RowKey**: `{ReceiptId}` *(Generated safely from the cleaned filename)*
- **Fields**: `ReceiptId`, `Username`, `MerchantName` *(AI Cleaned)*, `TotalAmount` *(float)*, `TransactionDate`, `BlobUrl`.

### 2. Product Item Entity (`Type: "Product"`)
- **PartitionKey**: `{username}_Items_{ReceiptId}`
- **RowKey**: `Item_{index:03d}` *(e.g., `Item_000`, `Item_001`)*
- **Fields**: `ReceiptId`, `Username`, `ProductName`, `Price` *(float)*, `Category` *(AI Classified)*, `MerchantName`, `TransactionDate`.

---

## 🧠 AI Semantic Intelligence Under the Hood

### 🏬 Merchant Name Normalization
Receipts from the same retail chain often print different company headers due to franchises or legal entities. Azure OpenAI processes these strings deterministically (`temperature=0.0`) to unify your analytics:
- `Lidl sp. z.o. o. sp. k.` ➡️ **Lidl**
- `BDO 000002265 Lidl sp. z o. o. sp. K.` ➡️ **Lidl**
- `Jeronimo Martins Polska S.A.` ➡️ **Biedronka**

### 🛒 Product Categorization
Instead of writing thousands of rigid dictionary regex rules, GPT-4o analyzes the semantic meaning of messy checkout abbreviations and maps them into one of the allowed categories:
`[spozywcze podstawowe, mieso i ryby, warzywa owoce, napoje, zwierzeta, dziecko, nabiał, chemia i kosmetyki, inne]`

---

## 🚀 CI/CD Pipeline & Security (GitHub Actions)

The repository includes an automated deployment workflow located in `.github/workflows/azure-functions-deploy.yml`. 

### Security Framework: Token-Based RBAC
Instead of using legacy, vulnerable `publish-profile` XML basic credentials (which are often blocked by Azure's modern security baselines), this project implements **Token-Based RBAC via an Azure Service Principal**.

The service principal was provisioned using Azure CLI with the **Principle of Least Privilege**:
```bash
az ad sp create-for-rbac \
  --name "GitHub-Function-Deployer" \
  --role contributor \
  --scopes /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/receipt-scanner-rg \
  --json-auth
```
This restricts the GitHub deployment bot's access exclusively to the `receipt-scanner-rg` resource group. The output configuration is stored securely inside **GitHub Repository Secrets** as `AZURE_CREDENTIALS`.

Every `git push origin main` automatically triggers the GitHub runner to resolve Python dependencies, install packages from `requirements.txt` into `.python_packages`, authenticate via `azure/login@v2`, and deploy the package directly to Azure.

---

## 📁 Project Directory Structure

```text
├── .github/
│   └── workflows/
│       └── azure-functions-deploy.yml  # GitHub Actions CI/CD automation
├── host.json                            # Azure Functions host configuration
├── local.settings.json                  # Local environment variables (Git ignored)
├── requirements.txt                     # Application dependencies
├── function_app.py                      # Main backend logic & Blob Trigger orchestrator
└── .gitignore                           # Strict exclusion list (.venv, caches, secrets)
```

---

## ⚙️ Environment Variables Required

To run this function app in production, the following keys must be configured under the **Environment Variables / Application Settings** of your Azure Function App:

| Variable Name | Description |
|---|---|
| `DOCUMENT_INTELLIGENCE_ENDPOINT` | The endpoint URL of your Azure AI Document Intelligence resource. |
| `DOCUMENT_INTELLIGENCE_KEY` | The API Key for your Azure AI Document Intelligence resource. |
| `AZURE_OPENAI_ENDPOINT` | The endpoint URL of your Azure OpenAI resource. |
| `AZURE_OPENAI_KEY` | The API Key for your Azure OpenAI resource. |
| `AZURE_OPENAI_DEPLOYMENT` | The deployment name of your GPT model (e.g., gpt-4o). |

---
*Developed as a modern, production-ready Serverless Cloud Architecture project.*