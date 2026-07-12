import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';
import express, { Request, Response } from 'express';
import cors from 'cors';
import dotenv from 'dotenv';

dotenv.config();

const API_KEY = process.env.BRAVE_API_KEY;
if (!API_KEY) {
  throw new Error('BRAVE_API_KEY environment variable is required');
}

const PORT = process.env.PORT || 3001;

// Map sessionId -> SSEServerTransport so POST /messages can route to the right session.
const transports = new Map<string, SSEServerTransport>();

class BraveSearchServer {
  private server: Server;
  private expressApp: express.Express;

  constructor() {
    this.server = new Server(
      {
        name: 'brave-search-mcp',
        version: '0.1.0',
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );

    this.expressApp = express();
    this.expressApp.use(cors());
    this.expressApp.use(express.json());

    this.setupToolHandlers();
    this.setupSSEEndpoints();

    process.on('SIGINT', async () => {
      await this.server.close();
      process.exit(0);
    });
  }

  private setupToolHandlers() {
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [
        {
          name: 'brave_web_search',
          description: 'Performs a web search using the Brave Search API',
          inputSchema: {
            type: 'object',
            properties: {
              query: {
                type: 'string',
                description: 'Search query (max 400 chars, 50 words)',
              },
              count: {
                type: 'number',
                description: 'Number of results (1-20, default 10)',
                default: 10,
              },
            },
            required: ['query'],
          },
        },
      ],
    }));

    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      if (request.params.name !== 'brave_web_search') {
        throw new McpError(
          ErrorCode.MethodNotFound,
          `Unknown tool: ${request.params.name}`
        );
      }

      const { query, count = 10 } = request.params.arguments as {
        query: string;
        count?: number;
      };

      const searchParams = new URLSearchParams({
        q: query,
        count: Math.min(Math.max(1, count), 20).toString(),
      });

      const response = await fetch(
        `https://api.search.brave.com/res/v1/web/search?${searchParams}`,
        {
          method: 'GET',
          headers: {
            Accept: 'application/json',
            'Accept-Encoding': 'gzip',
            'X-Subscription-Token': API_KEY || '',
          },
        }
      );

      if (!response.ok) {
        throw new McpError(
          ErrorCode.InternalError,
          `Brave API error: HTTP ${response.status}`
        );
      }

      const results = await response.json();

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify(results, null, 2),
          },
        ],
      };
    });
  }

  private setupSSEEndpoints() {
    /**
     * GET /sse
     * The Python MCP client connects here to open the SSE stream.
     * SSEServerTransport owns the wire protocol: it sends the mandatory
     * `endpoint` event (with the POST URL including ?sessionId=<id>) and
     * then keeps the connection alive. We must NOT write anything to `res`
     * before calling transport.start().
     */
    this.expressApp.get('/sse', async (req: Request, res: Response) => {
      const transport = new SSEServerTransport('/messages', res);

      transports.set(transport.sessionId, transport);

      res.on('close', () => {
        transports.delete(transport.sessionId);
      });

      // server.connect() already calls transport.start() internally.
      // Do NOT call transport.start() again — the SDK throws
      // "SSEServerTransport already started!" on a second call, which
      // closes the response and causes the Python client to see
      // "Connection closed".
      await this.server.connect(transport);
    });

    /**
     * POST /messages?sessionId=<id>
     * The Python MCP client POSTs JSON-RPC messages here.
     * Route to the matching transport; it parses the body and dispatches to
     * the MCP Server's request handlers.
     */
    this.expressApp.post('/messages', async (req: Request, res: Response) => {
      const sessionId = req.query['sessionId'] as string | undefined;

      if (!sessionId) {
        res.status(400).json({ error: 'Missing sessionId query parameter' });
        return;
      }

      const transport = transports.get(sessionId);
      if (!transport) {
        res.status(404).json({ error: `No active session: ${sessionId}` });
        return;
      }

      await transport.handlePostMessage(req, res, req.body);
    });
  }

  async run() {
    this.expressApp.listen(PORT, () => {
      console.error(`Brave Search MCP SSE server listening on port ${PORT}`);
    });
  }
}

const server = new BraveSearchServer();
server.run().catch(console.error);
