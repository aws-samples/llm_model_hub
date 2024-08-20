// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useState,useEffect } from "react";
import {
    FormField,
    Box,
    SpaceBetween,
    Input,
    Button,
    Modal,
  } from "@cloudscape-design/components";
// import { useChatData } from "./common-components";
import { useSettingCtx } from "./common-components";
import { useTranslation } from "react-i18next";
import { useLocalStorage } from '../commons/use-local-storage';



export const params_local_storage_key = "model-hub-setting-panel";
const username = 'default'
const SettingsPanel = ()=>{
    const { t } = useTranslation();
    const [localStoredParams, setLocalStoredParams] = useLocalStorage<Record<string,any>|null>(
      params_local_storage_key+username,
      null
    );
    // const {modelParams, setModelParams } = useChatData();
   
      const [ak, setAWSAk] = useState(
        localStoredParams?.ak || ''
      );
      const [sk, setAWSSk] = useState(
        localStoredParams?.sk || ''
      );
      const [region, setRegion] = useState(
        localStoredParams?.region || ''
      );
      const [sagemakerRole, setSagemakerRole] = useState(
        localStoredParams?.sagemakerRole || ''
      );

    return (
        <SpaceBetween direction="vertical" size="l">
        <FormField label={"AWS_ACCESS_KEY_ID"}>
          <Input
            onChange={({ detail }) => {
              setAWSAk(detail.value);
              setLocalStoredParams({
                ...localStoredParams,
                ak: detail.value,
              });
            }}
            value={ak}
          />
        </FormField>
        <FormField label={"AWS_SECRET_KEY"}>
          <Input
            onChange={({ detail }) => {
              setAWSSk(detail.value);
              setLocalStoredParams({
                ...localStoredParams,
                sk: detail.value,
              });
            }}
            value={sk}
          />
        </FormField>
        <FormField label={"Region"}>
          <Input
            onChange={({ detail }) => {
              setRegion(detail.value);
              setLocalStoredParams({
                ...localStoredParams,
                region: detail.value,
              });
            }}
            value={region}
          />
        </FormField>
        <FormField label={"SageMaker Execution Role"}>
          <Input
            onChange={({ detail }) => {
              setSagemakerRole(detail.value);
              setLocalStoredParams({
                ...localStoredParams,
                sagemakerRole: detail.value,
              });
            }}
            value={sagemakerRole}
          />
        </FormField>
</SpaceBetween>
    );
}

const ModelSettings =({href,modelSettingVisible,setModelSettingVisible}:{href:string,modelSettingVisible:boolean,setModelSettingVisible:(value:boolean)=>void}) =>{
    // console.log(href);
    const { t } = useTranslation();
    return (
        <Modal
          onDismiss={() => setModelSettingVisible(false)}
          visible={modelSettingVisible}
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="link" onClick={ ()=> setModelSettingVisible(false)}>{t('close')}</Button>
                <Button variant="primary" href={href} onClick={ ()=> 
                {
                  setModelSettingVisible(false);
                }}>{t('confirm')}</Button>
              </SpaceBetween>
            </Box>
          }
          header={t('settings')}
        >
          <SettingsPanel/>
        </Modal>
      );
}

export default ModelSettings;