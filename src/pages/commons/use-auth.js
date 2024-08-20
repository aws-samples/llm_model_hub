// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useState, useEffect, useContext, createContext } from "react";
import {useLocalStorage} from "./use-local-storage";
import {remotePost} from '../../common/api-gateway';
const localStoreKey = 'modelhub_credentials'
const authContext = createContext();
// Provider component that wraps your app and makes auth object ...
// ... available to any child component that calls useAuth().
export function ProvideAuth({ children }) {
    const auth = useProvideAuth();
    // console.log('ProvideAuth',auth);
    return <authContext.Provider value={auth}>{children}</authContext.Provider>;
  }

export function useAuthSignout () {
    const auth = useProvideAuth();
    return auth.signout;
}


export function useAuthToken(){
  const auth = useAuth();
  const [local_stored_tokendata] = useLocalStorage(localStoreKey,null);
  const user = auth.user?auth.user:local_stored_tokendata;
  const token = user.token;
  return {'token':'Bearer '+token}
}


export function useAuthUserInfo(){
    const auth = useAuth();
    const [local_stored_tokendata] = useLocalStorage(localStoreKey,null)
    const user = auth.user?auth.user:local_stored_tokendata;
    return {
          username:user?user.username:undefined,
          company:user?user.company:undefined,
          groupname:user?user.groupname:undefined,
          token:user?user.token:undefined,
        };
  }

export function useAuthorizedHeader(){
    const auth = useAuth();
    const [local_stored_tokendata] = useLocalStorage(localStoreKey,null)
    const authdata = auth.user?auth.user:local_stored_tokendata;
    const token = authdata.token;
    return {
            'Content-Type':'application/json;charset=utf-8',
            'Authorization':'Bearer '+token
        };
  }

// Hook for child components to get the auth object ...
// ... and re-render when it changes.
export const useAuth = () => {
    return useContext(authContext);
  };
  
  // Provider hook that creates auth object and handles state
function useProvideAuth() {
    const [user, setUser] = useState();
    const [,setToken] = useLocalStorage(localStoreKey,null);
    // Wrap any Firebase methods we want to use making sure ...
    // ... to save the user to state.
    const signin = async (email, password) => {
      const data = await remotePost({ username: email, password: password }, 'login');
      setToken(data.response);
      setUser(data.response);
      return data.response;
    };
  
    const signout = () => {
      setToken(null);
      return setUser(null);
    };
  
    const signup =(username,email,password) =>{
      // return remote_signup(username,email,password).then(data => data);
    };

    const confirm_signup = (username,confirmcode)=>{
      // return remote_confirm_signup(username,confirmcode).then(data => data);
    };

  
    // Return the user object and auth methods
    return {
      user,
      signin,
      signout,
      signup,
      confirm_signup
      
    };
  } 