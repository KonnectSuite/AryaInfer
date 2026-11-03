// serve/web/mcp-catalog.js - the servers the page can add in one click.
//
// Every entry is something AryaInfer's MCP client can actually do (serve/mcp.py): a program it starts (stdio) or a
// Streamable-HTTP address with optional fixed headers. Servers that only work through an OAuth sign-in are left out
// rather than offered and failing. `params` fill {{placeholders}} in `args`; an optional argument whose placeholder
// is left empty is dropped with its "--flag". `env` names the variables a server needs and is stored with it in
// mcp-servers.json. Package names move with their projects: `docs` is where the current command is stated.
const MCP_CATALOG = [
  // ---------------------------------------------------------------- Core
  {
    id: "filesystem", title: "Filesystem", icon: "filesystem", category: "Core", transport: "stdio",
    summary: "Read, write and search inside the folders you allow.",
    command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem", "{{folder}}"],
    params: [{key: "folder", label: "Folder", required: true, placeholder: "C:\\Users\\me\\Documents",
              help: "The only place the server may touch. Add a second server for another folder."}],
    needs: ["Node.js"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
    match: ["server-filesystem"],
  },
  {
    id: "git", title: "Git", icon: "git", category: "Core", transport: "stdio",
    summary: "Status, diffs, log, branches and commits of a repository.",
    command: "uvx", args: ["mcp-server-git", "--repository", "{{repo}}"],
    params: [{key: "repo", label: "Repository folder", required: true, placeholder: "C:\\Users\\me\\code\\project",
              help: "The working tree the tools read and commit in."}],
    needs: ["Python", "uv"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/git",
    match: ["mcp-server-git"],
  },
  {
    id: "fetch", title: "Fetch", icon: "globe", category: "Core", transport: "stdio",
    summary: "Fetch a URL and convert the page to Markdown for the model.",
    command: "uvx", args: ["mcp-server-fetch"],
    needs: ["Python", "uv"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/fetch",
    match: ["mcp-server-fetch"],
  },
  {
    id: "memory", title: "Memory", icon: "brain", category: "Core", transport: "stdio",
    summary: "A persistent knowledge graph the model can add to and query.",
    command: "npx", args: ["-y", "@modelcontextprotocol/server-memory"],
    needs: ["Node.js"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/memory",
    match: ["server-memory"],
  },
  {
    id: "time", title: "Time", icon: "clock", category: "Core", transport: "stdio",
    summary: "The current time and timezone conversion.",
    command: "uvx", args: ["mcp-server-time"],
    needs: ["Python", "uv"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/time",
    match: ["mcp-server-time"],
  },
  {
    id: "sequential-thinking", title: "Sequential thinking", icon: "cube", category: "Core", transport: "stdio",
    summary: "A scratchpad for structured, multi-step reasoning.",
    command: "npx", args: ["-y", "@modelcontextprotocol/server-sequential-thinking"],
    needs: ["Node.js"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking",
    match: ["sequential-thinking", "sequentialthinking"],
  },
  {
    id: "everything", title: "Everything", icon: "mcp", category: "Core", transport: "stdio",
    summary: "The reference server: every MCP feature, useful for testing a setup.",
    command: "npx", args: ["-y", "@modelcontextprotocol/server-everything"],
    needs: ["Node.js"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/everything",
    match: ["server-everything"],
  },

  // ---------------------------------------------------------------- Developer tools
  {
    id: "github", title: "GitHub", icon: "github", category: "Developer tools", transport: "stdio",
    summary: "Repositories, issues, pull requests and code search.",
    command: "npx", args: ["-y", "@modelcontextprotocol/server-github"],
    env: [{key: "GITHUB_PERSONAL_ACCESS_TOKEN", label: "Personal access token", secret: true, required: true,
           placeholder: "ghp_…", help: "A token with the scopes the tools you want need (repo, issues)."}],
    needs: ["Node.js", "API key"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/github",
    match: ["server-github"],
  },
  {
    id: "gitlab", title: "GitLab", icon: "gitlab", category: "Developer tools", transport: "stdio",
    summary: "Projects, merge requests and issues on GitLab.",
    command: "npx", args: ["-y", "@modelcontextprotocol/server-gitlab"],
    env: [{key: "GITLAB_PERSONAL_ACCESS_TOKEN", label: "Personal access token", secret: true, required: true,
           placeholder: "glpat-…"}],
    needs: ["Node.js", "API key"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/gitlab",
    match: ["server-gitlab"],
  },
  {
    id: "sentry", title: "Sentry", icon: "sentry", category: "Developer tools", transport: "stdio",
    summary: "Issues, events and stack traces from Sentry projects.",
    command: "npx", args: ["-y", "@modelcontextprotocol/server-sentry"],
    env: [{key: "SENTRY_AUTH_TOKEN", label: "Auth token", secret: true, required: true},
          {key: "SENTRY_ORG", label: "Organisation slug", required: false, placeholder: "my-org"}],
    needs: ["Node.js", "API key"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/sentry",
    match: ["server-sentry"],
  },
  {
    id: "docker", title: "Docker", icon: "docker", category: "Developer tools", transport: "stdio",
    summary: "List containers, start and stop them, and read logs.",
    command: "npx", args: ["-y", "mcp-server-docker"],
    needs: ["Node.js", "Docker"], docs: "https://github.com/ckreiling/mcp-server-docker",
    match: ["mcp-server-docker"],
  },
  {
    id: "kubernetes", title: "Kubernetes", icon: "kubernetes", category: "Developer tools", transport: "stdio",
    summary: "Query pods, deployments and events on a cluster.",
    command: "npx", args: ["-y", "mcp-server-kubernetes"],
    needs: ["Node.js", "kubectl"], docs: "https://github.com/Flux159/mcp-server-kubernetes",
    match: ["mcp-server-kubernetes"],
  },
  {
    id: "context7", title: "Context7", icon: "book", category: "Developer tools", transport: "stdio",
    summary: "Up-to-date library documentation the model can look up.",
    command: "npx", args: ["-y", "@upstash/context7-mcp"],
    needs: ["Node.js"], docs: "https://github.com/upstash/context7",
    match: ["context7"],
  },
  {
    id: "e2b", title: "E2B Sandbox", icon: "cube", category: "Developer tools", transport: "stdio",
    summary: "Run code in a disposable cloud sandbox.",
    command: "npx", args: ["-y", "@e2b/mcp-server"],
    env: [{key: "E2B_API_KEY", label: "API key", secret: true, required: true}],
    needs: ["Node.js", "API key"], docs: "https://github.com/e2b-dev/mcp-server",
    match: ["e2b"],
  },

  // ---------------------------------------------------------------- Browsers
  {
    id: "playwright", title: "Playwright", icon: "playwright", category: "Browsers", transport: "stdio",
    summary: "Drive a real browser: navigate, click, type, screenshot and read pages.",
    command: "npx", args: ["-y", "@playwright/mcp@latest"],
    needs: ["Node.js"], docs: "https://github.com/microsoft/playwright-mcp",
    match: ["@playwright/mcp", "playwright-mcp"],
  },
  {
    id: "puppeteer", title: "Puppeteer", icon: "puppeteer", category: "Browsers", transport: "stdio",
    summary: "Browser automation and JavaScript execution on pages.",
    command: "npx", args: ["-y", "@modelcontextprotocol/server-puppeteer"],
    needs: ["Node.js"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/puppeteer",
    match: ["server-puppeteer"],
  },
  {
    id: "chrome", title: "Chrome DevTools", icon: "chrome", category: "Browsers", transport: "stdio",
    summary: "Inspect a live Chrome instance: console, network, screenshots.",
    command: "npx", args: ["-y", "chrome-devtools-mcp@latest"],
    needs: ["Node.js", "Chrome"], docs: "https://github.com/ChromeDevTools/chrome-devtools-mcp",
    match: ["chrome-devtools"],
  },

  // ---------------------------------------------------------------- Data
  {
    id: "postgres", title: "PostgreSQL", icon: "postgres", category: "Data", transport: "stdio",
    summary: "Read-only SQL against a Postgres database.",
    command: "npx", args: ["-y", "@modelcontextprotocol/server-postgres", "{{database_url}}"],
    params: [{key: "database_url", label: "Database URL", required: true,
              placeholder: "postgresql://user:password@localhost:5432/db",
              help: "It is stored in mcp-servers.json with the other server settings; scope the account to the " +
                    "tables the model should see."}],
    needs: ["Node.js"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/postgres",
    match: ["server-postgres"],
  },
  {
    id: "sqlite", title: "SQLite", icon: "sqlite", category: "Data", transport: "stdio",
    summary: "Query and inspect a SQLite database file.",
    command: "uvx", args: ["mcp-server-sqlite", "--db-path", "{{path}}"],
    params: [{key: "path", label: "Database file", required: true, placeholder: "C:\\Users\\me\\data\\notes.db"}],
    needs: ["Python", "uv"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite",
    match: ["mcp-server-sqlite"],
  },

  // ---------------------------------------------------------------- Knowledge and communication
  {
    id: "notion", title: "Notion", icon: "notion", category: "Knowledge", transport: "stdio",
    summary: "Search and read Notion pages and databases.",
    command: "npx", args: ["-y", "@notionhq/notion-mcp-server"],
    env: [{key: "NOTION_TOKEN", label: "Integration token", secret: true, required: true, placeholder: "ntn_…"}],
    needs: ["Node.js", "API key"], docs: "https://github.com/makenotion/notion-mcp-server",
    match: ["notion-mcp-server"],
  },
  {
    id: "slack", title: "Slack", icon: "slack", category: "Knowledge", transport: "stdio",
    summary: "Read channels and post messages in a Slack workspace.",
    command: "npx", args: ["-y", "@modelcontextprotocol/server-slack"],
    env: [{key: "SLACK_BOT_TOKEN", label: "Bot token", secret: true, required: true, placeholder: "xoxb-…"},
          {key: "SLACK_TEAM_ID", label: "Team ID", required: true, placeholder: "T01234567"}],
    needs: ["Node.js", "API key"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/slack",
    match: ["server-slack"],
  },
  {
    id: "brave", title: "Brave Search", icon: "brave", category: "Knowledge", transport: "stdio",
    summary: "Web and local search through Brave's API.",
    command: "npx", args: ["-y", "@modelcontextprotocol/server-brave-search"],
    env: [{key: "BRAVE_API_KEY", label: "API key", secret: true, required: true}],
    needs: ["Node.js", "API key"], docs: "https://github.com/modelcontextprotocol/servers/tree/main/src/brave-search",
    match: ["server-brave-search"],
  },
];

window.MCP_CATALOG = MCP_CATALOG;
