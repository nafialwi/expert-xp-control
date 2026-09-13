const fs=require('fs');
if(!fs.existsSync('package.json')) process.exit(2);
console.log('NODE_VERIFY_CLEAR');
