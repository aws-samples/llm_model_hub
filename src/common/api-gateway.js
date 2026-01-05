// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import axios from 'axios';
// console.log(process.env)
// Use relative path for API calls, which will be proxied to backend
// In development: requests go to http://localhost:3000/v1/* -> proxied to http://localhost:8000/v1/*
// In production: requests go to same host, need nginx/ALB to route /v1/* to backend
export const API_ENDPOINT = process.env.REACT_APP_API_ENDPOINT || '/v1';
export const API_KEY = process.env.REACT_APP_API_KEY || '';
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";

export const remotePost = async(formdata,path,stream=false) =>{
   console.log(formdata);
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

export const remoteGet = async(path) => {
    const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${API_KEY}`
    };

    try {
        const resp = await axios.get(`${API_ENDPOINT}/${path}`, { headers });

        if (resp.statusText === 'OK') {
            return resp.data;
        } else {
            console.log(`Server error:${resp.status}`);
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
