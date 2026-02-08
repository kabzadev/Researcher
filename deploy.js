#!/usr/bin/env node
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// Deploy using SWA CLI
const token = 'ca81cac7aef3cca3a7aa7611d5ad564de0d0e9504c7ab220312b41433b0c955c02-cb1dbfb0-bc94-4407-8f65-d1dee743dce900f080001010220f';
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
