import azure.functions as func
import logging
import json
import os
from datetime import datetime, timezone
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient

app = func.FunctionApp()

STORAGE_CONNECTION_STRING = os.environ.get("STORAGE_CONNECTION_STRING")

# Helper function to get BlobServiceClient
def get_blob_service_client():
    return BlobServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)

# Helper function to get TableServiceClient
def get_table_service_client():
    return TableServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)

# 1. Process Image Function (Event Grid Triggered)
@app.event_grid_trigger(arg_name="event")
def process_image(event: func.EventGridEvent):
    logging.info(f"Processing Event Grid event: {event.id}")
    event_data = event.get_json()
    blob_url = event_data.get('url', '')
    
    # Extract blob name from URL
    blob_name = blob_url.split('/')[-1]
    
    metadata = {
        "blob_name": blob_name,
        "blob_url": blob_url,
        "content_type": event_data.get('contentType', 'unknown'),
        "file_size_bytes": event_data.get('contentLength', 0),
        "processed_timestamp": datetime.now(timezone.utc).isoformat(),
        "simulated_dimensions": "1920x1080",
        "thumbnail_ref": f"https://simulated-cdn.net/thumbs/{blob_name}"
    }

    try:
        blob_service_client = get_blob_service_client()
        result_blob_name = f"result-{blob_name}.json"
        blob_client = blob_service_client.get_blob_client(container="image-results", blob=result_blob_name)
        blob_client.upload_blob(json.dumps(metadata, indent=2), overwrite=True)
        logging.info(f"Successfully processed and stored results for {blob_name}")
    except Exception as e:
        logging.error(f"Error processing image {blob_name}: {str(e)}")

# 2. Audit Log Function (Event Grid Triggered)
@app.event_grid_trigger(arg_name="event")
def audit_log(event: func.EventGridEvent):
    logging.info(f"Audit Logging Event: {event.id}")
    event_data = event.get_json()
    blob_url = event_data.get('url', '')
    blob_name = blob_url.split('/')[-1]

    try:
        table_service_client = get_table_service_client()
        table_client = table_service_client.create_table_if_not_exists("processinglog")
        
        entity = {
            "PartitionKey": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "RowKey": f"{blob_name}-{event.id}",
            "BlobUrl": blob_url,
            "EventType": event.event_type,
            "ContentType": event_data.get('contentType', 'unknown'),
            "Timestamp": datetime.now(timezone.utc).isoformat()
        }
        table_client.create_entity(entity=entity)
        logging.info(f"Audit record created for {blob_name}")
    except Exception as e:
        logging.error(f"Error writing audit log: {str(e)}")

# 3. Get Results Endpoint (HTTP Triggered)
@app.route(route="get-results", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_results(req: func.HttpRequest) -> func.HttpResponse:
    try:
        blob_service_client = get_blob_service_client()
        container_client = blob_service_client.get_container_client("image-results")
        
        results = []
        for blob in container_client.list_blobs():
            blob_client = container_client.get_blob_client(blob.name)
            content = blob_client.download_blob().readall()
            results.append(json.loads(content))

        return func.HttpResponse(json.dumps(results), mimetype="application/json", status_code=200)
    except Exception as e:
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json")

# 4. Get Audit Log Endpoint (HTTP Triggered)
@app.route(route="get-audit-log", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_audit_log(req: func.HttpRequest) -> func.HttpResponse:
    try:
        table_service_client = get_table_service_client()
        table_client = table_service_client.get_table_client("processinglog")
        
        logs = []
        for entity in table_client.list_entities():
            logs.append({
                "PartitionKey": entity["PartitionKey"],
                "RowKey": entity["RowKey"],
                "BlobUrl": entity.get("BlobUrl"),
                "EventType": entity.get("EventType"),
                "ContentType": entity.get("ContentType"),
                "Timestamp": entity.get("Timestamp")
            })

        return func.HttpResponse(json.dumps(logs), mimetype="application/json", status_code=200)
    except Exception as e:
        return func.HttpResponse(json.dumps([]), status_code=200, mimetype="application/json")

# 5. Health Endpoint
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"status": "healthy", "service": "PhotoPipe Function App"}),
        mimetype="application/json",
        status_code=200
    )