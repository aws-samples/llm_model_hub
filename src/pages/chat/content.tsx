// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, {  useState, useEffect } from "react";
import { ChatDataCtx } from "./common-components";
import {
  Header,
  SpaceBetween,
  ContentLayout,
  Alert,
} from "@cloudscape-design/components";
import ConversationsPanel from "./conversations";
import { useTranslation } from "react-i18next";
import {params_local_storage_key} from "./common-components";
import { type ModelParamProps,defaultModelParams } from "./prompt-panel";
import { remotePost } from "../../common/api-gateway";
import { useLocalStorage } from '../commons/use-local-storage';

const Content = ({endpoint}:{endpoint:string|undefined}) => {
  const [modelParams, setModelParams] = useState<ModelParamProps>(defaultModelParams);
  const [loading, setLoading] = useState(false);
  const [conversations, setConversations] = useState([]);
  const [feedBackModalVisible,setFeedBackModalVisible] = useState(false);
  const [modalData,setModalData] = useState({});
  const [stopFlag,setStopFlag] = useState(false);
  const [newChatLoading, setNewChatLoading] = useState(false);
  const { t } = useTranslation();
  const [localStoredMsgItems, setLocalStoredMsgItems] = useLocalStorage(
    params_local_storage_key + '-msgitems-'+endpoint,
    []
  );
  const [maxConversations, setMaxConversations] = useState<number>(10);

  const [msgItems, setMsgItems] = useState(localStoredMsgItems);
  const [endpointName, setEndpointName] = useState<string | undefined>(endpoint);
  const [modelName, setModelName] = useState<string>();


  useEffect(() => {

    const params = {
      "page_size": 100,
      "page_index": 1,
      "query_terms": { "endpoint_name": endpoint }
    }
    //如果设置了endpoint
    endpointName && (
      remotePost(params, 'list_endpoints').then((resp) => {
        resp.endpoints.map((item: any) => setModelName(item.model_name))
      }).catch(err => {
        console.log(err);
      }))
  }, [endpoint]);

  useEffect(()=>{
    setModelParams((prev) =>({
      ...prev,
    }))
  },[]);


  return (
    <ChatDataCtx.Provider
      value={{
        msgItems,
        setMsgItems,
        modelParams,
        setModelParams,
        loading,
        setLoading,
        conversations,
        setConversations,
        feedBackModalVisible,
        setFeedBackModalVisible,
        modalData,
        setModalData,
        stopFlag,
        setStopFlag,
        newChatLoading, 
        setNewChatLoading,
        endpointName,
        setEndpointName,
        modelName,
        setModelName,
        maxConversations,
        setMaxConversations
      }}
    >
      <ContentLayout header={<Header variant="h1">{t("chat")}</Header>}>
          <ConversationsPanel/>
      </ContentLayout>
    </ChatDataCtx.Provider>
  );
};

export default Content;
