# StorePilot AI

AI product-page generator for Shopify.

Flow: product URL → import product data/images → generate conversion copy with AI → preview → publish to Shopify.

## Environment variables

- `AI_PROVIDER=gemini` or `openai`
- `AI_API_KEY=...`
- `AI_MODEL=gemini-2.5-flash`
- `OPENAI_BASE_URL=https://api.openai.com/v1` (optional)
- `SHOPIFY_STORE=your-store.myshopify.com`
- `SHOPIFY_TOKEN=...`
- `SHOPIFY_PUBLICATION_ID=...` (optional)

Never commit real API keys or Shopify tokens.
