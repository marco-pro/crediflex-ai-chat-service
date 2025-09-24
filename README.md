# CrediFlex AI Chat Service

## Overview

The CrediFlex AI Chat Service is a conversational AI backend that provides intelligent assistance to CrediFlex suppliers. It uses OpenAI's Responses API with a dashboard-configured prompt to maintain conversation context through internal thread management.

## Key Implementation Decisions

### Why Responses API Instead of Threads API?

- **Dashboard Integration**: Uses pre-configured prompts from OpenAI dashboard
- **Simplified Architecture**: No complex thread management with OpenAI
- **Cost Efficiency**: Single API call per request
- **Full Control**: Internal conversation state management

### Internal Thread Management

Instead of using OpenAI's Threads API, we implemented our own thread system:

- **UUID-based Thread IDs**: Each conversation gets a unique `chat_thread_ai`
- **In-Memory Storage**: `THREAD_STORAGE` dictionary (production: Redis/DB)
- **Conversation History**: Last 20 messages stored per thread
- **Auto-cleanup**: Threads expire after 24 hours

## How It Works

### 1. Conversation Flow

```
Frontend → Backend → OpenAI Responses API
   ↓         ↓            ↓
Current   Retrieves    Receives
Message   History      Response
   ↓         ↓            ↓
Same ID ← Stores New ← Returns
Returned   Messages     Response
```

### 2. History Management

**Frontend sends minimal data:**
```json
{
  "query": "clientes activos?",
  "chat_thread_ai": "uuid-123-456"  // Optional for first message
}
```

**Backend manages everything:**
- Retrieves conversation history from `THREAD_STORAGE`
- Builds complete context for OpenAI
- Stores new message pairs
- Returns same `chat_thread_ai` for continuity

### 3. Context Injection

The backend injects conversation history into the OpenAI API payload:

```
HISTORIAL DE CONVERSACIÓN:
Usuario: clientes activos?
Asistente: ACTIVOS (2): METRO CONSTRUCTION LLC, Urban Supply Co

CONTEXTO DEL PROVEEDOR:
[Supplier data summary]

PREGUNTA ACTUAL DEL USUARIO: Sí, muéstrame detalles
```

## API Endpoints

### Production Endpoint

**POST** `/chat`
- **Purpose**: Main chat endpoint for production use
- **Request**: `query`, `chat_thread_ai` (optional), `context` (supplier data)
- **Response**: AI response + same `chat_thread_ai`

### Test Endpoint

**POST** `/test`
- **Purpose**: Same as `/chat` but with pre-configured demo data
- **Request**: `query`, `chat_thread_ai` (optional)
- **Response**: AI response + same `chat_thread_ai`
- **Demo Data**: Includes sample business clients, orders, settlements

### Thread Management

- **GET** `/threads/{chat_thread_ai}` - Get thread info
- **GET** `/threads/{chat_thread_ai}/messages` - Get conversation history
- **DELETE** `/threads/{chat_thread_ai}` - Delete thread
- **GET** `/threads` - List all active threads

### Health Check

**GET** `/health`
- Returns service status, active threads count, and configuration

## Deployment

### Railway Production URL
```
https://crediflex-ai-chat-service.up.railway.app
```

This README provides a high-level overview of:

##  **Key Sections**

1. **Overview & Implementation Decisions** - Why we chose this approach
2. **How It Works** - Simple flow explanation
3. **API Endpoints** - All available endpoints with purposes
4. **Deployment** - Railway URL and environment setup
5. **Frontend Integration** - Required changes and examples
6. **Important Notes** - Critical information about persistence and context
7. **Testing** - Quick test commands
8. **Architecture Benefits** - Why this design is better
9. **Future Enhancements** - Planned improvements
10. **Troubleshooting** - Common issues and solutions

The document is concise but comprehensive, focusing on the essential information needed to understand and work with the service! 🚀

## Frontend Integration

### Required Changes

1. **API URL**: Use Railway deployment URL
2. **Field Names**: Change `thread_id` to `chat_thread_ai`
3. **Request Structure**: Include `chat_thread_ai` in subsequent requests

### Example Implementation

```javascript
const sendMessage = async (userMessage) => {
  const requestBody = {
    query: userMessage,
    chat_thread_ai: currentThreadId,  // Updated field name
    context: contextData
  };

  const response = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestBody)
  });

  const data = await response.json();
  setCurrentThreadId(data.chat_thread_ai);  // Store for next request
  
  // Add messages to chat UI
  setMessages(prev => [
    ...prev,
    { role: 'user', content: userMessage },
    { role: 'assistant', content: data.response }
  ]);
};
```

## Important Notes

### Thread Persistence

- **Same ID Returned**: Every response returns the same `chat_thread_ai`
- **Context Maintained**: AI remembers previous conversation
- **Server Restart**: Threads are lost (in-memory storage)
- **Production**: Will use Redis/DB for persistence

### Conversation Context

- **History Injection**: Last 10 messages sent to OpenAI
- **Message Limit**: Maximum 20 messages per thread
- **Auto-cleanup**: Threads expire after 24 hours of inactivity

### Error Handling

- **Graceful Degradation**: Fallback responses for API failures
- **Input Validation**: Required field checking
- **Timeout Management**: 60-second timeout for OpenAI requests

## Testing

### Quick Test Commands

```bash
# First message
curl -X POST "https://crediflex-ai-chat-service.up.railway.app/chat" \
  -H "Content-Type: application/json" \
  -d '{"query": "clientes activos?"}'

# Follow-up message (use chat_thread_ai from previous response)
curl -X POST "https://crediflex-ai-chat-service.up.railway.app/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Sí, muéstrame detalles",
    "chat_thread_ai": "uuid-from-previous-response"
  }'

# Test endpoint with demo data
curl -X POST "https://crediflex-ai-chat-service.up.railway.app/test" \
  -H "Content-Type: application/json" \
  -d '{"query": "¿Cómo va mi programa de crédito?"}'
```

## Architecture Benefits

### 1. **Simplified Design**
- No OpenAI Threads API complexity
- Direct Responses API usage
- Internal conversation management

### 2. **Cost Efficient**
- Single API call per request
- No thread creation overhead
- Efficient context injection

### 3. **Flexible**
- Custom thread management
- Easy to extend with Redis/DB
- Dashboard prompt integration

### 4. **Reliable**
- No external thread dependencies
- Graceful error handling
- Consistent response format

## Future Enhancements

### Short Term
- **Redis Integration**: Replace in-memory storage
- **Database Persistence**: Thread backup and recovery
- **Enhanced Logging**: Better debugging capabilities

### Long Term
- **Thread Analytics**: Usage metrics and insights
- **Conversation Summarization**: Long conversation handling
- **Multi-language Support**: International expansion

## Troubleshooting

### Common Issues

1. **Context Lost**: Ensure `chat_thread_ai` is sent in subsequent requests
2. **New Thread Each Time**: Check if using `/test` instead of `/chat`
3. **API Errors**: Verify OpenAI API key and prompt ID configuration

### Debug Information

The service includes logging for:
- Thread creation and lookup
- Conversation history injection
- API request/response details

## Conclusion

This implementation provides a robust, scalable solution for conversational AI in the CrediFlex ecosystem. By using OpenAI's Responses API with internal thread management, we achieve optimal performance while maintaining conversation context and integrating seamlessly with dashboard-configured prompts.

The architecture is designed for easy maintenance, extension, and deployment, making it suitable for both development and production environments.
