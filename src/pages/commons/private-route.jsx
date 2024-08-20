import React from "react";
import { useAuth } from "./use-auth";
import { Outlet, Navigate, useLocation } from "react-router-dom";
import { useLocalStorage } from './use-local-storage';
const localStoreKey = 'modelhub_credentials'

// export default function PrivateRoute({ redirectPath }) {
//   const auth = useAuth();
//   const isAuthenticated = auth.user ? auth.user.isAuthorized : false;
//   // console.log("PrivateRoute:",JSON.stringify(auth));
//   return isAuthenticated ? <Outlet /> : <Navigate to={redirectPath} replace />;
// }

function isTokenExpired(exptime) {
  let d1 = new Date();
  let d2 = new Date(
    d1.getUTCFullYear(),
    d1.getUTCMonth(),
    d1.getUTCDate(),
    d1.getUTCHours(),
    d1.getUTCMinutes(),
    d1.getUTCSeconds()
  );
  const current = Number(d2) / 1000;
  //  console.log("current time",current);
  return current > exptime;
}

export function RequireAuth({ children, redirectPath, requireAdmin }) {
  //use localstorage
  const [local_stored_tokendata] = useLocalStorage(localStoreKey, null);
  const location = useLocation();

  //use context
  const auth = useAuth();
  console.log('useAuth()',auth);
  //if context is empty, try to use local storage
  const user = auth.user? auth.user:local_stored_tokendata;
  // console.log(user);
  let isAuthenticated = user?user.isAuthorized:false;

  //if it is only granted to admin
  if (isAuthenticated && requireAdmin && user.groupname !== 'admin') {
      isAuthenticated = false;
  }
 
  if (isAuthenticated) {
    return children;
  } else return <Navigate to={redirectPath} state={{ from: location }} />;
}
