import React, { useEffect } from "react";
import './App.css';
import {
  BrowserRouter as Router,
  Routes,
  Route,
  useNavigate,
} from "react-router-dom";

import Dashboard from './pages/dashboard';
import JobTable from './pages/jobs'
import NotFound from './pages/commons/no-found';
import CreateJobApp from './pages/jobs/create-job';
import JobDetailApp from './pages/jobs/job-detail';
import EndpointsTable from './pages/endpoints';
import ClustersTable from './pages/clusters';
import CreateClusterApp from './pages/clusters/create-cluster';
import ClusterDetailApp from './pages/clusters/cluster-detail';
import ChatBot from './pages/chat/chatmain';
import { ProvideAuth, useAuthSignout} from "./pages/commons/use-auth";
import  {RequireAuth} from './pages/commons/private-route';
import LoginPage from "./pages/login/login";
import {SimpleNotifications} from "./pages/commons/use-notifications";

function App() {
  return (
    <div className="App">
      <SimpleNotifications>
      <Router>
      <ProvideAuth>
        <Routes>
          <Route path="/" element={<RequireAuth requireAdmin={false}  redirectPath="/login"><Dashboard/></RequireAuth>} />
          <Route path="/login" element={<LoginPage/>} />
          <Route path="/jobs" element={<RequireAuth requireAdmin={false}  redirectPath="/login"><JobTable/></RequireAuth>} />
          <Route path="/jobs/createjob" element={<RequireAuth requireAdmin={false}  redirectPath="/login"><CreateJobApp/></RequireAuth>} />
          <Route path="/jobs/:id" element={<RequireAuth requireAdmin={false}  redirectPath="/login"><JobDetailApp/></RequireAuth>} />
          <Route path="/endpoints" element={<RequireAuth requireAdmin={false}  redirectPath="/login"><EndpointsTable/></RequireAuth>} />
          <Route path="/clusters" element={<RequireAuth requireAdmin={false}  redirectPath="/login"><ClustersTable/></RequireAuth>} />
          <Route path="/clusters/create" element={<RequireAuth requireAdmin={false}  redirectPath="/login"><CreateClusterApp/></RequireAuth>} />
          <Route path="/clusters/:id" element={<RequireAuth requireAdmin={false}  redirectPath="/login"><ClusterDetailApp/></RequireAuth>} />
          <Route path='/chat' element={<RequireAuth requireAdmin={false}  redirectPath="/login"><ChatBot/></RequireAuth>} />
          <Route path='/chat/:endpoint' element={<RequireAuth requireAdmin={false}  redirectPath="/login"><ChatBot/></RequireAuth>} />
          <Route path="*" element={<NotFound/>} />
          <Route path="/signout" element={<SignOut/>}/>
        </Routes>
        </ProvideAuth>
      </Router>
      </SimpleNotifications>
    </div>
  );
}

function SignOut(){
  const signout = useAuthSignout();
  const navigate = useNavigate();
  useEffect(()=>{
    navigate("/login");
    signout();
  },[])
  return <h1>sign out</h1>;
}


export default App;
