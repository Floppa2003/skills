# Firecrawl 2: account selection and recovery

## Connection identity

This package adds workflows to an existing native ChatGPT App connection. Its
App binding is recorded in `.app.json`; preserve that binding when editing the
skills. A plugin named Firecrawl 2 does not by itself establish that a different
Firecrawl account or team was selected. Use the connection belonging to this
package, even when another installed package has the same display name.

## Route tools to this connection

Use the host-provided tools whose plugin provenance identifies **Firecrawl 2**.
Tool names in the packaged skills omit host-specific prefixes. Reuse this
plugin's authenticated connection; do not copy credentials or select tools from
the official Firecrawl plugin or another FireCrawl connector merely because
the unprefixed tool name matches. If provenance is ambiguous, resolve it before
using account data or spending credits.

## Select an account

1. In the browser profile used for connecting the plugin, open
   [Firecrawl sign-in](https://www.firecrawl.dev/signin) and sign in to the
   intended Firecrawl account. If another account is active, the user should
   sign out of Firecrawl and sign in to the intended account.
2. Open **Settings → Plugins**, select this App-backed **Firecrawl 2**, and use
   its displayed connection controls. Inspect the actual screen before naming
   a Connect or Reconnect button. If a similarly named card only offers
   **Open in desktop app**, return to this native App's entry; an uploaded
   portable MCP package is not proof of a registered ChatGPT web connection.
   The configured MCP endpoint is a server URL, not a web login page.
3. In Firecrawl's OAuth flow, verify the active account and choose the intended
   team. Usage is charged to the team owning this connection. Let the user
   complete credentials, MFA, and consent in the provider's UI.
4. If the plugin was already connected to the wrong account, reconnect only
   Firecrawl 2 through the host's connection controls. Changing the website's
   active session does not itself replace an existing OAuth connection.

Do not request passwords, API keys, or OAuth tokens in chat or store them in
the plugin. Preserve other Firecrawl connections. Follow host security gates;
do not try alternate browser surfaces to bypass a blocked navigation.

## Verify without starting paid data work

After the host completes connection, discover this connection's actual tools.
Use `firecrawl_credit_usage` with `{"view":"current"}` when available; otherwise
use another suitable authenticated read-only account operation such as
`firecrawl_monitor_list` with a small limit. Check the result before reporting
authentication success. Tool visibility alone is not a successful connection.

A balance or an empty monitor list does not establish the user's email, team
identity, or whether two connections use different accounts. Confirm the
account and team in the provider's consent/settings UI when that matters.
If two connections return identical balances and billing-period timestamps,
report that as a reason to check the selected team, not proof of account
identity. Do not mark the second-account setup complete on that evidence alone.
Distinguish authentication errors from timeouts, service failures, empty data,
and depleted credits. Do not retry repeatedly while user login is pending.

If no Firecrawl 2 sidebar is available, use this connection's tools in chat.
The official Firecrawl app's sidebar may belong to a different connection.

## Sources

- https://docs.firecrawl.dev/authentication
- https://docs.firecrawl.dev/mcp-server/oauth
- https://docs.firecrawl.dev/integrations/chatgpt-codex
- https://www.firecrawl.dev/app/settings?tab=mcp
- https://help.openai.com/en/articles/20001494-connecting-and-managing-app-accounts-in-chatgpt
- https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt
