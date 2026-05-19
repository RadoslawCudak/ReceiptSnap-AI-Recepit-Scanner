import azure.functions as func
import logging
import os
import time
from typing import Any
from azure.identity import DefaultAzureCredential
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from azure.data.tables import TableClient
from openai import AzureOpenAI

app = func.FunctionApp()

# --- FUNKCJA POMOCNICZA 1: CZYSZCZENIE NAZWY SKLEPU PRZEZ AZURE OPENAI ---
def clean_merchant_name(raw_merchant_name: str) -> str:
    if not raw_merchant_name or raw_merchant_name == "Nieznany Sklep":
        return "Nieznany Sklep"
        
    try:
        client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_KEY"],
            api_version="2024-02-01"
        )
        
        response = client.chat.completions.create(
            model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            messages=[
                {
                    "role": "system", 
                    "content": "Jesteś ekspertem od normalizacji danych z paragonów. Twoim zadaniem jest uproszczenie podanej nazwy firmy/sklepu do jej powszechnie znanej, czystej nazwy marki handlowej (np. 'Lidl sp. z o.o.' zamień na 'Lidl', 'Jeronimo Martins Polska S.A.' lub 'Biedronka Sp. z o.o.' na 'Biedronka', 'Auchan Polska' na 'Auchan'). Usuń formy prawne (sp. z o.o., S.A.), numery BDO, NIP, adresy i zbędne dopiski. Zwróć TYLKO I WYŁĄCZNIE samą czystą nazwę (zaczynając z wielkiej litery), bez żadnych dodatkowych słów czy znaków interpunkcyjnych."
                },
                {"role": "user", "content": f"Nazwa z paragonu: {raw_merchant_name}"}
            ],
            max_tokens=10,
            temperature=0.0
        )
        
        raw_content = response.choices[0].message.content
        cleaned_name = raw_content.strip() if raw_content else raw_merchant_name
        logging.info(f"AI oczyściło nazwę sklepu: '{raw_merchant_name}' -> '{cleaned_name}'")
        return cleaned_name
    except Exception as e:
        logging.error(f"Błąd OpenAI przy czyszczeniu nazwy sklepu: {str(e)}")
        return raw_merchant_name


# --- FUNKCJA POMOCNICZA 2: KATEGORYZACJA PRZEZ AZURE OPENAI ---
def ask_ai_for_category(product_name: str) -> str:
    try:
        client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_KEY"],
            api_version="2024-02-01"
        )
        allowed_categories = "spozywcze podstawowe, mieso i ryby, warzywa i owoce, napoje, zwierzeta, dziecko, nabiał, chemia i kosmetyki, przekąski i słodycze,alkohol, inne"
        
        response = client.chat.completions.create(
            model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            messages=[
                {
                    "role": "system", 
                    "content": f"Jesteś ekspertem od analizy paragonów. Twoim zadaniem jest przypisać podany produkt do JEDNEJ z następujących kategorii: [{allowed_categories}]. Odpowiedz TYLKO I WYŁĄCZNIE nazwą kategorii, bez kropki, bez dodatkowych słów czy wyjaśnień. Jeśli produkt kompletnie nie pasuje, zwróć: inne."
                },
                {"role": "user", "content": f"Produkt: {product_name}"}
            ],
            max_tokens=15,
            temperature=0.0
        )
        raw_content = response.choices[0].message.content
        category = raw_content.strip().lower() if raw_content else "inne"
        return category
    except Exception as e:
        logging.error(f"Błąd OpenAI: {str(e)}")
        return "inne"


# --- GŁÓWNA FUNKCJA TRIGGERA ---
@app.blob_trigger(arg_name="myblob", path="receipts/{username}/{name}", connection="AzureWebJobsStorage")
def process_receipt(myblob: func.InputStream):
    full_path = str(myblob.name)
    blob_name_parts = full_path.split('/')
    
    username = blob_name_parts[1] if len(blob_name_parts) >= 2 else "unknown_user"
    filename = blob_name_parts[-1].lower()
    
    logging.info(f"--- Managed Identity: Procesowanie dla użytkownika: {username}, plik: {filename} ---")

    try:
        endpoint = os.environ["DOCUMENT_INTELLIGENCE_ENDPOINT"]
        ai_key = os.environ["DOCUMENT_INTELLIGENCE_KEY"]
        account_url = "https://receiptscannerstorecrc.table.core.windows.net"
        table_name = "ReceiptsData"

        credential = DefaultAzureCredential()

        # --- GENEROWANIE RECEIPT_ID Z NAZWY PLIKU ---
        raw_filename_nowext = os.path.splitext(blob_name_parts[-1])[0]
        unique_receipt_id = raw_filename_nowext.replace(" ", "_").replace(".", "_")
        logging.info(f"Wygenerowane ReceiptId z nazwy pliku: {unique_receipt_id}")

        blob_bytes = myblob.read()

        client = DocumentAnalysisClient(endpoint, AzureKeyCredential(ai_key))
        poller = client.begin_analyze_document("prebuilt-receipt", blob_bytes)
        result = poller.result()

        if result.documents:
            table_client = TableClient(endpoint=account_url, table_name=table_name, credential=credential)

            for receipt in result.documents:
                fields: Any = receipt.fields
                
                merchant = fields.get("MerchantName")
                total = fields.get("Total")
                date = fields.get("TransactionDate")

                final_total = 0.0
                if total and hasattr(total, 'value') and total.value is not None:
                    try:
                        final_total = float(total.value)
                    except (ValueError, TypeError):
                        final_total = 0.0

                raw_merchant_name = str(merchant.value) if merchant and hasattr(merchant, 'value') and merchant.value else "Nieznany Sklep"
                transaction_date = str(date.value) if date and hasattr(date, 'value') and date.value else "Brak daty"

                # --- WYWOŁANIE INTELIGENTNEGO CZYSZCZENIA NAZWY SKLEPU ---
                merchant_name = clean_merchant_name(raw_merchant_name)

                # 1. Zapis nagłówka
                summary_entity = {
                    "PartitionKey": f"{username}_Summary",
                    "RowKey": unique_receipt_id,
                    "ReceiptId": unique_receipt_id,
                    "Username": str(username),
                    "Type": "Summary",
                    "MerchantName": merchant_name,  # <-- Czysta nazwa (np. Lidl)
                    "TotalAmount": final_total,
                    "TransactionDate": transaction_date,
                    "BlobUrl": str(myblob.uri)
                }
                table_client.create_entity(entity=summary_entity)

                # 2. Zapis produktów
                items = fields.get("Items")
                if items and hasattr(items, 'value') and items.value:
                    for index, item in enumerate(items.value):
                        item_desc = item.value.get("Description")
                        product_name = str(item_desc.value) if item_desc and hasattr(item_desc, 'value') and item_desc.value else f"Product_{index}"
                        
                        item_total = item.value.get("TotalPrice")
                        product_price = 0.0
                        if item_total and hasattr(item_total, 'value') and item_total.value is not None:
                            try:
                                product_price = float(item_total.value)
                            except (ValueError, TypeError):
                                product_price = 0.0

                        detected_category = ask_ai_for_category(product_name)

                        item_entity = {
                            "PartitionKey": f"{username}_Items_{unique_receipt_id}",
                            "RowKey": f"Item_{index:03d}",
                            "ReceiptId": unique_receipt_id,
                            "Username": str(username),
                            "Type": "Product",
                            "ProductName": product_name,
                            "Price": product_price,
                            "Category": detected_category, 
                            "MerchantName": merchant_name,  # <-- Ta sama czysta nazwa powielona w produkcie
                            "TransactionDate": transaction_date
                        }
                        table_client.create_entity(entity=item_entity)
                    
                    logging.info(f"Zapisano czyste dane w tabeli dla użytkownika {username}, sklep: {merchant_name}")

    except Exception as e:
        logging.error(f"Błąd przetwarzania: {str(e)}")