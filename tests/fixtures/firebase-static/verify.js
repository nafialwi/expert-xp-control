const fs=require('fs');
if(!fs.existsSync('firebase.json')) process.exit(2);
if(!fs.existsSync('public/index.html')) process.exit(3);
console.log('FIREBASE_STATIC_VERIFY_CLEAR');
