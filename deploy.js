#!/usr/bin/env node
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// Deploy using SWA CLI
// SECURITY: Token must be provided via AZURE_SWA_TOKEN environment variable
const token = process.env.AZURE_SWA_TOKEN;
if (!token) {
  console.error('Error: AZURE_SWA_TOKEN environment variable is required');
  console.error('Set it with: export AZURE_SWA_TOKEN=your_token_here');
  process.exit(1);
}

const distPath = path.join(__dirname, 'frontend', 'dist');

console.log('Deploying to Azure Static Web Apps...');
console.log('Dist path:', distPath);
console.log('Files:', fs.readdirSync(distPath));

try {
  const result = execSync(
    `npx -y @azure/static-web-apps-cli@2.0.8 deploy ${distPath} --deployment-token ${token} --env production --no-use-keychain`,
    { stdio: 'inherit', cwd: __dirname, timeout: 120000 }
  );
  console.log('Deployment complete!');
} catch (err) {
  console.error('Deployment failed:', err.message);
  process.exit(1);
}
