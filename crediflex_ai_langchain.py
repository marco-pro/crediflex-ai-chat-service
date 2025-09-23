# crediflex_ai_langchain.py
import os
import uuid
import httpx
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import List, Dict, Optional
import json

# Load environment variables
load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = "https://api.openai.com/v1"
# Your custom prompt ID from the dashboard
CREDIFLEX_PROMPT_ID = "pmpt_68d1cdbd447081958a372a0c10fdf06001bdc9bb0333b459"

# Thread storage (in production, use Redis or database)
THREAD_STORAGE = {}
THREAD_EXPIRY_HOURS = 24

# OpenAI Responses API client
class OpenAIResponsesClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = OPENAI_BASE_URL
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    
    async def create_response(self, thread_id: str, input_text: str, context_data: Dict = None) -> Dict:
        """Create a response using the Responses API with your dashboard-configured prompt"""
        
        # Prepare the input with context
        input_content = input_text
        if context_data:
            supplier_summary = self._summarize_supplier_data(context_data)
            input_content = f"CONTEXTO DEL PROVEEDOR:\n{supplier_summary}\n\nPREGUNTA DEL USUARIO: {input_text}"
        
        payload = {
            "model": "gpt-4.1-mini",  # Using your dashboard model
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": input_content
                        }
                    ]
                }
            ],
            "text": {
                "format": {
                    "type": "text"
                }
            },
            "reasoning": {},
            "tools": [],
            "temperature": 1.00,  # Using your dashboard temperature
            "max_output_tokens": 2048,  # Using your dashboard max tokens
            "top_p": 1.00,  # Using your dashboard top_p
            "store": True,  # Using your dashboard store setting
            "include": ["web_search_call.action.sources"],
            # Reference your custom prompt from the dashboard
            "prompt_id": CREDIFLEX_PROMPT_ID
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/responses",
                    headers=self.headers,
                    json=payload,
                    timeout=60.0
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                raise HTTPException(status_code=e.response.status_code, detail=f"OpenAI API error: {e.response.text}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Request failed: {str(e)}")
    
    def _summarize_supplier_data(self, data: Dict) -> str:
        """Summarize supplier data for context"""
        try:
            business_clients = data.get('business_clients', [])
            
            # Group clients by status
            status_groups = {}
            for client in business_clients:
                status = client.get('approval_status', 'unknown')
                if status not in status_groups:
                    status_groups[status] = []
                status_groups[status].append({
                    'name': client.get('company_name', 'Sin nombre'),
                    'email': client.get('email', ''),
                    'credit_limit': client.get('credit', {}).get('credit_limit', 0)
                })

            summary = f"""
RESUMEN DEL PROGRAMA DE CRÉDITO:

CLIENTES POR STATUS DE APROBACIÓN:
"""
            
            for status, clients in status_groups.items():
                status_name = {
                    'active': 'ACTIVOS',
                    'pending': 'PENDIENTES', 
                    'rejected': 'RECHAZADOS',
                    'suspended': 'SUSPENDIDOS'
                }.get(status, status.upper())
                
                summary += f"{status_name} ({len(clients)}):\n"
                for client in clients:
                    summary += f"  • {client['name']}\n"
                summary += "\n"
            
            # Rest of metrics...
            orders = data.get('orders', [])
            settlements = data.get('settlements', [])
            
            total_revenue = sum(p.get('amount', 0) for p in settlements)
            summary += f"""
MÉTRICAS GENERALES:
- Total clientes: {len(business_clients)}
- Ingresos totales: ${total_revenue:,.2f}
- Órdenes procesadas: {len(orders)}
"""
            
            return summary

        except Exception as e:
            return f"Error procesando datos: {str(e)}"

# Thread management functions
def create_thread():
    """Create a new conversation thread"""
    thread_id = str(uuid.uuid4())
    THREAD_STORAGE[thread_id] = {
        "created_at": datetime.now(),
        "last_activity": datetime.now(),
        "messages": [],
        "context": {}
    }
    return thread_id

def get_thread(thread_id: str) -> Optional[Dict]:
    """Get thread data"""
    return THREAD_STORAGE.get(thread_id)

def update_thread(thread_id: str, user_message: str, assistant_response: str, context: Dict = None):
    """Update thread with new messages"""
    if thread_id not in THREAD_STORAGE:
        return
    
    thread = THREAD_STORAGE[thread_id]
    thread["last_activity"] = datetime.now()
    
    # Update context if provided
    if context:
        thread["context"] = context
    
    # Add messages to thread
    thread["messages"].append({
        "role": "user",
        "content": user_message,
        "timestamp": datetime.now().isoformat()
    })
    thread["messages"].append({
        "role": "assistant", 
        "content": assistant_response,
        "timestamp": datetime.now().isoformat()
    })
    
    # Keep only last 20 messages to prevent context overflow
    if len(thread["messages"]) > 20:
        thread["messages"] = thread["messages"][-20:]

def cleanup_expired_threads():
    """Remove expired threads"""
    expired_time = datetime.now() - timedelta(hours=THREAD_EXPIRY_HOURS)
    expired_threads = [
        thread_id for thread_id, data in THREAD_STORAGE.items()
        if data["last_activity"] < expired_time
    ]
    for thread_id in expired_threads:
        del THREAD_STORAGE[thread_id]

# Initialize OpenAI client
openai_client = OpenAIResponsesClient(OPENAI_API_KEY)

# Create FastAPI app
app = FastAPI(
    title="CrediFlex AI with Responses API",
    version="2.0",
    description="AI Assistant for CrediFlex suppliers using OpenAI Responses API with dashboard-configured prompt",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify specific domains
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

@app.post("/chat")
async def chat_endpoint(request_data: Dict):
    """Main chat endpoint using Responses API with thread management"""
    try:
        # Get or create thread
        thread_id = request_data.get("thread_id")
        if not thread_id:
            thread_id = create_thread()
        elif not get_thread(thread_id):
            # Thread doesn't exist, create new one
            thread_id = create_thread()
        
        # Get thread data
        thread = get_thread(thread_id)
        
        # Get user query
        query = request_data.get("query", "")
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        # Get context data
        context_data = request_data.get("context", {})
        
        # Create response using OpenAI Responses API
        response_data = await openai_client.create_response(
            thread_id=thread_id,
            input_text=query,
            context_data=context_data
        )
        
        # Extract response text
        response_text = ""
        if "output" in response_data and response_data["output"]:
            for output_item in response_data["output"]:
                if output_item.get("type") == "text" and "text" in output_item:
                    response_text += output_item["text"]
        
        if not response_text:
            response_text = "Lo siento, no pude generar una respuesta. Por favor, intenta de nuevo."
        
        # Update thread with new messages
        update_thread(thread_id, query, response_text, context_data)
        
        return {
            "response": response_text,
            "thread_id": thread_id,
            "timestamp": int(datetime.now().timestamp()),
            "model": "gpt-4.1-mini (Dashboard Prompt)",
            "status": "success",
            "openai_response_id": response_data.get("id")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        return {
            "error": str(e),
            "status": "error"
        }

@app.post("/test")
async def test_endpoint(request_data: Dict):
    """Test endpoint with demo data"""
    demo_data = {
        "query": request_data.get("query", "¿Cómo va mi programa de crédito?"),
        "context": {
            "business_clients": [
                {
                    "client_id": "cli_9876543210.1111",
                    "company_name": "METRO CONSTRUCTION LLC",
                    "email": "finance@metroconstruction.com",
                    "phone": "+1-555-0123",
                    "approval_status": "active",
                    "credit": {
                        "credit_limit": 100000,
                        "credit_used": 75000
                    }
                },
                {
                    "client_id": "cli_8765432109.2222", 
                    "company_name": "Urban Supply Co",
                    "email": "orders@urbansupply.biz",
                    "phone": "+1-555-0234",
                    "approval_status": "active",
                    "credit": {
                        "credit_limit": 60000,
                        "credit_used": 35000
                    }
                },
                {
                    "client_id": "cli_7654321098.3333",
                    "company_name": "PACIFIC RETAIL GROUP",
                    "email": "purchasing@pacificretail.com",
                    "phone": "+1-555-0345",
                    "approval_status": "pending",
                    "credit": {
                        "credit_limit": 0,
                        "credit_used": 0
                    }
                },
                {
                    "client_id": "cli_6543210987.4444",
                    "company_name": "Midwest Manufacturing Inc",
                    "email": "procurement@midwest-mfg.com", 
                    "phone": "+1-555-0456",
                    "approval_status": "rejected",
                    "credit": {
                        "credit_limit": 0,
                        "credit_used": 0
                    }
                }
            ],
            "orders": [
                {
                    "client_id": "cli_9876543210.1111",
                    "amount": 35000,
                    "payment_status": "completed_on_time",
                    "created": 1734659051,
                    "external_order_id": "PO-2024-001",
                    "supplier_account": "sup_1234567890.123",
                    "currency": "USD",
                    "status": "completed"
                },
                {
                    "client_id": "cli_8765432109.2222",
                    "amount": 22000,
                    "payment_status": "completed_late", 
                    "created": 1736285243,
                    "external_order_id": "PO-2024-002",
                    "supplier_account": "sup_1234567890.123",
                    "currency": "USD",
                    "status": "completed"
                },
                {
                    "client_id": "cli_9876543210.1111",
                    "amount": 40000,
                    "payment_status": "due",
                    "created": 1737384627,
                    "external_order_id": "PO-2024-003",
                    "supplier_account": "sup_1234567890.123",
                    "currency": "USD",
                    "status": "pending"
                }
            ],
            "settlements": [
                {
                    "amount": 34300,
                    "settlement_date": 1738866140,
                    "supplier_account": "sup_1234567890.123",
                    "currency": "USD",
                    "status": "completed",
                    "settlement_id": "set_abc123def456"
                },
                {
                    "amount": 21560,
                    "settlement_date": 1739212444,
                    "supplier_account": "sup_1234567890.123", 
                    "currency": "USD",
                    "status": "completed",
                    "settlement_id": "set_def456ghi789"
                },
                {
                    "amount": 39200,
                    "settlement_date": 1739816995,
                    "supplier_account": "sup_1234567890.123",
                    "currency": "USD", 
                    "status": "pending",
                    "settlement_id": "set_ghi789jkl012"
                }
            ],
            "credit_requests": [
                {
                    "client_id": "cli_9876543210.1111",
                    "request_total": 40000,
                    "expires": 1740700800,
                    "external_order_id": "PO-2024-003",
                    "supplier_account": "sup_1234567890.123",
                    "currency": "USD",
                    "description": "Industrial equipment purchase",
                    "status": 0,
                    "created": 1737395614
                },
                {
                    "client_id": "cli_8765432109.2222",
                    "request_total": 18500,
                    "expires": 1741305600,
                    "external_order_id": "PO-2024-004",
                    "supplier_account": "sup_1234567890.123",
                    "currency": "USD",
                    "description": "Office supplies bulk order",
                    "status": 0,
                    "created": 1737482000
                }
            ]
        }
    }
    
    return await chat_endpoint(demo_data)

# Thread management endpoints
@app.get("/threads/{thread_id}")
async def get_thread_info(thread_id: str):
    """Get thread information"""
    thread = get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    return {
        "thread_id": thread_id,
        "created_at": thread["created_at"].isoformat(),
        "last_activity": thread["last_activity"].isoformat(),
        "message_count": len(thread["messages"]),
        "status": "success"
    }

@app.get("/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str):
    """Get thread messages"""
    thread = get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    return {
        "thread_id": thread_id,
        "messages": thread["messages"],
        "status": "success"
    }

@app.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str):
    """Delete a thread"""
    if thread_id not in THREAD_STORAGE:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    del THREAD_STORAGE[thread_id]
    return {"message": "Thread deleted successfully", "status": "success"}

@app.get("/threads")
async def list_threads():
    """List all active threads"""
    cleanup_expired_threads()
    threads = []
    for thread_id, data in THREAD_STORAGE.items():
        threads.append({
            "thread_id": thread_id,
            "created_at": data["created_at"].isoformat(),
            "last_activity": data["last_activity"].isoformat(),
            "message_count": len(data["messages"])
        })
    
    return {"threads": threads, "status": "success"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": int(datetime.now().timestamp()),
        "active_threads": len(THREAD_STORAGE),
        "api_version": "2.0 (Dashboard Prompt)",
        "prompt_id": CREDIFLEX_PROMPT_ID
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)