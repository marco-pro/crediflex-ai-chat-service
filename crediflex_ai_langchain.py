# crediflex_ai_langchain.py
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.output_parsers import StrOutputParser
from langserve import add_routes
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import List, Dict
import json

# Configuración
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Sistema de prompt
SYSTEM_PROMPT = """Eres un asistente especializado para usuarios del dashboard de proveedores de CrediFlex.

CONTEXTO:
- CrediFlex es un SaaS que ayuda a proveedores a manejar programas de crédito para sus clientes empresariales
- Ayudas a proveedores a analizar sus datos de clientes, órdenes y pagos

ESTRUCTURA DE DATOS:
- business_clients[] = clientes empresariales con diferentes approval_status
- orders[] = transacciones realizadas
- settlements[] = pagos recibidos por el proveedor
- credit_requests[] = solicitudes de crédito pendientes

ANÁLISIS DE CLIENTES - STATUS DISPONIBLES:
Los business_clients tienen estos approval_status posibles:
- "active": Cliente aprobado y activo para crédito
- "pending": Cliente en proceso de aprobación
- "rejected": Cliente rechazado para crédito
- "suspended": Cliente suspendido temporalmente

CAPACIDADES QUE TIENES:
✅ Listar clientes por status de aprobación
✅ Mostrar métricas de cartera y crédito
✅ Analizar performance de pagos
✅ Reportes de órdenes y cobranza
✅ Análisis de pipeline de ventas
✅ Segmentación de clientes activos/pendientes/rechazados

REGLAS DE RESPUESTA:
1. SIEMPRE responde en español
2. Para consultas de datos (listas, métricas), proporciona la información directamente
3. Sé conciso inicialmente, luego pregunta si quieren más detalles
4. SOLO rechaza preguntas no relacionadas con: clientes, crédito, ventas, pagos, cobranza, cartera

EJEMPLOS DE CONSULTAS VÁLIDAS:
- "Enlista los clientes por status"
- "¿Cuántos clientes activos tengo?"
- "Muéstrame los clientes pendientes de aprobación"
- "¿Cuál es mi cartera vencida?"
- "Lista de órdenes pagadas tarde"

FORMATO DE RESPUESTA PARA LISTAS:
Cuando te pidan listar clientes por status, organiza así:
**ACTIVOS (X):**
- Nombre Cliente 1
- Nombre Cliente 2

**PENDIENTES (X):**
- Nombre Cliente 3

**RECHAZADOS (X):**
- Nombre Cliente 4
"""

def summarize_supplier_data(data: Dict) -> str:
    try:
        business_clients = data.get('business_clients', [])
        
        # Agrupar clientes por status
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
        
        # Resto de métricas...
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

# Crear el chain de LangChain
def create_crediflex_chain():
    # Modelo
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.3,
        api_key=OPENAI_API_KEY
    )
    
    # Template del prompt simplificado
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "ROL DEL USUARIO: {user_role}\n\nDATOS DEL PROVEEDOR:\n{supplier_summary}\n\nPREGUNTA DEL USUARIO: {query}")
    ])
    
    # Chain
    chain = prompt | llm | StrOutputParser()
    
    return chain

# Función para procesar input
def process_input(input_data: Dict) -> Dict:
    """Procesa el input y prepara el contexto"""
    query = input_data.get("query", "")
    supplier_data = input_data.get("context", {})
    user_context = input_data.get("user", {})
    conversation_history = input_data.get("conversation_history", [])
    
    # Convertir historial a mensajes de LangChain
    chat_history = []
    for msg in conversation_history[:-1]:  # Excluir el mensaje actual
        if msg["role"] == "user":
            chat_history.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            chat_history.append(AIMessage(content=msg["content"]))
    
    # Preparar contexto
    supplier_summary = summarize_supplier_data(supplier_data)
    user_role = user_context.get("role", "admin")
    
    return {
        "query": query,
        "chat_history": chat_history,
        "supplier_summary": supplier_summary,
        "user_role": user_role
    }

# Crear la app FastAPI
app = FastAPI(
    title="CrediFlex AI with LangChain",
    version="1.0",
    description="AI Assistant for CrediFlex suppliers using LangChain",
)

# Agregar CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, especifica dominios específicos
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Crear el chain
crediflex_chain = create_crediflex_chain()

# Agregar rutas con LangServe
add_routes(
    app,
    crediflex_chain,
    path="/crediflex",
    input_type=Dict,
    playground_type="chat",
)

# Endpoint personalizado compatible con tu frontend actual
@app.post("/chat")
async def chat_endpoint(request_data: Dict):
    try:
        # Procesar input
        processed_input = process_input(request_data)
        
        # Ejecutar chain
        response = await crediflex_chain.ainvoke(processed_input)
        
        return {
            "response": response,
            "supplier_summary": processed_input["supplier_summary"],
            "timestamp": 1234567890,
            "model": "CrediFlex AI with LangChain",
            "status": "success"
        }
    except Exception as e:
        return {
            "error": str(e),
            "status": "error"
        }

@app.post("/test")
async def test_endpoint(request_data: Dict):
    # Datos demo para CrediFlex
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
        },
        "user": {"role": request_data.get("role", "admin")},
        "conversation_history": request_data.get("conversation_history", [])
    }
    
    return await chat_endpoint(demo_data)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)