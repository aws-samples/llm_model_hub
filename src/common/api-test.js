const axios = require('axios');


const API_ENDPOINT = `http://127.0.0.1:8000/v1`
const API_KEY = '123456'
const remotePost = async(formdata,path) =>{
    console.log('api:',`${API_ENDPOINT}/${path}`)
    const headers = {'Content-Type': 'application/json', 
        'Authorization': `Bearer ${API_KEY}`
        };
    try {
        const resp = await axios.post(`${API_ENDPOINT}/${path}`,JSON.stringify(formdata), {headers});
        return resp.data;
    } catch (err) {
        throw err;
    }
}

remotePost({"page_size":30,"page_index":1},'list_jobs').then(data => {
    console.log(data);
}).catch(err => {
    console.log(err);
})