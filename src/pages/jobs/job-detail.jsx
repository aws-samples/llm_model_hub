// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useRef, useState } from 'react';
// import { createRoot } from 'react-dom/client';
import { CustomAppLayout, Navigation, Notifications } from '../commons/common-components';
import {Breadcrumbs,createjobBreadcrumbs} from '../commons/breadcrumbs'

import { FormWithValidation} from './create-job/components/form';
import { useNavigate,useParams } from "react-router-dom";
import { remotePost } from '../../common/api-gateway';
import {
  Spinner
} from "@cloudscape-design/components";
import '../../styles/form.scss';


const JobDetailApp =() => {
  const { id } = useParams();
  const [toolsIndex, setToolsIndex] = useState(0);
  const [toolsOpen, setToolsOpen] = useState(false);
  const appLayout = useRef();
  const [notificationData, setNotificationData] = useState({});
  const [displayNotify, setDisplayNotify] = useState(false);
  const navigate = useNavigate();
  const [data, _setData] = useState();
  const [readOnly, setReadOnly] = useState(true);
  const [loading, setLoading] = useState(false);

  const loadHelpPanelContent = index => {
    setToolsIndex(index);
    setToolsOpen(true);
    appLayout.current?.focusToolsClose();
  };

  useEffect(()=>{
    const controller = new AbortController();
    remotePost({"job_id":id},'get_job')
        .then((res)=>{
            console.log(res.body);
            _setData(res.body);
        }).catch(err=>console.log(err));

    return ()=>{
        controller.abort();
    }

  },[]);

  return (
    <CustomAppLayout
      ref={appLayout}
      contentType="form"
      content={
        data?<FormWithValidation
          loadHelpPanelContent={loadHelpPanelContent}
          setNotificationData={setNotificationData}
          setDisplayNotify={setDisplayNotify}
          readOnly={readOnly}
          data={data}
          loading={loading}
          setLoading={setLoading}
          _setData={_setData}
          setReadOnly={setReadOnly}
          // header={<FormHeader readOnly={readOnly} loadHelpPanelContent={loadHelpPanelContent} />}
        />:(
          <Spinner size="large"/>
        )
      }
      breadcrumbs={<Breadcrumbs items={createjobBreadcrumbs}/>}
      navigation={<Navigation activeHref="#/jobs" />}
      // tools={ToolsContent[toolsIndex]}
      toolsOpen={toolsOpen}
      onToolsChange={({ detail }) => setToolsOpen(detail.open)}
      notifications={<Notifications 
        successNotification={displayNotify}
      data={notificationData}/>}
    />
  );
}


export default JobDetailApp;
