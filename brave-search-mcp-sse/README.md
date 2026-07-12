# Brave Search MCP with SSE Support

This is a Model Context Protocol (MCP) server that provides Brave Search capabilities with Server-Sent Events (SSE) integration. It can be deployed to Coolify and used as a real-time search service.

## Features

- Brave Search API integration through MCP
- Real-time search results using SSE
- Docker and Coolify ready
- TypeScript implementation
- Express.js SSE endpoint

## Prerequisites

- Brave Search API key
- Node.js 18+
- Docker (for containerized deployment)
- Coolify instance

## Local Development

1. Clone the repository
2. Create a `.env` file with your Brave API key:
   ```
   BRAVE_API_KEY=your_api_key_here
   PORT=3001
   ```
3. Install dependencies:
   ```bash
   npm install
   ```
4. Start development server:
   ```bash
   npm run dev
   ```

## Docker Deployment

1. Build and run using docker-compose:
   ```bash
   docker-compose up --build
   ```

## Coolify Deployment

1. In your Coolify dashboard, create a new service
2. Choose "Deploy from Source"
3. Configure the following:
   - Repository URL: Your repository URL
   - Branch: main
   - Build Command: `npm run build`
   - Start Command: `npm start`
   - Port: 3001
   - Environment Variables:
     - BRAVE_API_KEY=your_api_key_here
     - PORT=3001

## Using the SSE Integration

### SSE Endpoint
```
GET http://your-server:3001/sse
```

The SSE endpoint provides real-time search results. Connect to it using the EventSource API:

```javascript
const eventSource = new EventSource('http://your-server:3001/sse');

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // Handle the search results
  console.log(data);
};

eventSource.onerror = (error) => {
  console.error('SSE Error:', error);
  eventSource.close();
};
```

### Messages Endpoint
```
POST http://your-server:3001/messages
Content-Type: application/json

{
  "query": "your search query",
  "count": 10  // optional, default: 10, max: 20
}
```

Use this endpoint to trigger searches that will be broadcast to all connected SSE clients.

## MCP Usage

The server provides the following MCP tool:

- `brave_web_search`: Performs a web search using the Brave Search API
  ```typescript
  {
    query: string;    // Search query
    count?: number;   // Number of results (1-20, default: 10)
  }
  ```

## Error Handling

- The server broadcasts errors to all connected SSE clients
- Errors are formatted as:
  ```json
  {
    "type": "error",
    "error": "error message"
  }
  ```

## Notes

- The SSE connection will stay open until the client closes it
- Each search result is broadcast to all connected clients
- The server automatically handles disconnections and cleanup
- For production deployment, consider implementing authentication for the messages endpoint
