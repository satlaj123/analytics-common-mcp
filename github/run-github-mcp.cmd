@echo off
set "PATH=C:\Users\%USERNAME%\<YOUR_ORG_NAME>\2026\Software\NodeJs\node-v24.19.0-win-x64;%PATH"
set "NODE_OPTIONS=--use-system-ca"
npx -y @modelcontextprotocol/server-github
