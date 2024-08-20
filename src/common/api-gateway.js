// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import axios from 'axios';
// console.log(process.env)
export const API_ENDPOINT= process.env.REACT_APP_API_ENDPOINT;
export const API_KEY = process.env.REACT_APP_API_KEY;
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";

export const remotePost = async(formdata,path,stream=false) =>{
    const headers = {'Content-Type': 'application/json', 
        'Authorization': `Bearer ${API_KEY}`
        };

    const args =  stream ?{headers:headers,responseType:'stream'} :{headers:headers}
    try {
        const resp = await axios.post(`${API_ENDPOINT}/${path}`,JSON.stringify(formdata),args);
        
        if (resp.statusText === 'OK'){
            return stream?resp.body:resp.data
        } else{
            console.log(`Server error:${resp.status}`)
            throw `Server error:${resp.status}`;
        }

    } catch (err) {
        throw err;
    }
}

export const fetchPost = async (formData,path) => {
    const headers = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${API_KEY}`
    };
  
    try {
      const response = await fetch(`${API_ENDPOINT}/${path}`, {
        method: 'POST',
        headers: headers,
        body:JSON.stringify(formData),
        redirect: "follow",
      });
      return response;
    } catch (err) {
      throw err;
    }
  };
