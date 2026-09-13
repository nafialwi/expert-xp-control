const fs=require('fs');
if(!fs.existsSync('package.json')) process.exit(2);
console.log('NODE_POSTGRES_SOURCE_VERIFY_CLEAR');
