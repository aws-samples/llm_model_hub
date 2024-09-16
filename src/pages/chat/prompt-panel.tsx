// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState,useRef } from "react";
import {
  FormField,
  Container,
  Grid,
  Textarea,
  SpaceBetween,
  Toggle,
  Input,
  Button,
  FileUpload,
  ExpandableSection,
  Select,
  ColumnLayout,
  SelectProps
} from "@cloudscape-design/components";
import { remotePost } from "../../common/api-gateway";
import { useChatData, generateUniqueId } from "./common-components";
import { useTranslation } from "react-i18next";
import { useLocalStorage } from '../commons/use-local-storage';
import { params_local_storage_key } from "./common-components";
import {type MsgItemProps, type MessageDataProp} from './conversations';

const company = "default";
const username = 'default';
export interface ModelParamProps {
    temperature: number
    top_p:number
    max_tokens: number
    model_name: string|null
    model_name_opt: SelectProps.Options|null
    system_role_prompt: string
    use_stream:boolean
    chat_template:string
}
export interface ModelOptionProps{
      label:string
      value:string
}
export const defaultModelParams:ModelParamProps = {
  temperature: 0.1,
  top_p:0.95,
  max_tokens: 1024,
  model_name: null,
  model_name_opt: null,
  system_role_prompt: "",
  use_stream:true,
  chat_template: "{% if add_generation_prompt and messages[-1]['role'] != 'assistant' %}{{ '<|im_start|>assistant\n' }}{% endif %}"
};

function generateId() {
  const timestamp = new Date().getTime(); // Get the current timestamp in milliseconds
  const randomNumber = Math.random().toString(16).slice(2, 8);
  return `${timestamp}-${randomNumber}`;
}

const ExpandableSettingPanel = () => {
  const { t } = useTranslation();
  const {
    modelName,
    endpointName,
    setModelParams,
    maxConversations,
    setMaxConversations,
    setEndpointName,
    setModelName,
  } = useChatData();

  const [localStoredParams, setLocalStoredParams] = useLocalStorage<Record<string, any>|null>(
    params_local_storage_key + username,
    null
  );

  const [epselectedOption, setepSelectedOption] = useState <SelectProps.Option>({value: endpointName,label: endpointName});

  const [endpointsInfo, setEndpointsInfo] = useState <Record<string,any>[]>([]);

  const [tokenSize, settokenSize] = useState(
    localStoredParams?.max_tokens || defaultModelParams.max_tokens
  );
  const [temperatureValue, setTempValue] = useState(
    localStoredParams?.temperature || defaultModelParams.temperature
  );
  const [toppValue, setToppValue] = useState(
    localStoredParams?.top_p || defaultModelParams.top_p
  );

  const [systemRolePromptValue, setSystemRolePromptValue] = useState(
    localStoredParams?.system_role_prompt === undefined
          ? defaultModelParams.system_role_prompt
          : localStoredParams?.system_role_prompt,
  );

  const [chatTemplate, setChatTemplate] = useState(
    localStoredParams?.chat_template || defaultModelParams.chat_template
  );

  type StatusType = "finished" | "loading" | "error";

  const [loadStatus, setLoadStatus] = useState<StatusType>("loading");


  interface OptionsLoadItemsDetail {
      filteringText: string
      firstPage: boolean
      samePage: boolean
  }
  const handleLoadItems = async ({
    detail,
  }:{detail:OptionsLoadItemsDetail}) => {
    setLoadStatus("loading");
    try {
      //to do fetch endpoints
      const params = {
        "page_size":100,
        "page_index":1,
        "query_terms":{"endpoint_status":"INSERVICE"}
      }
      const response = await remotePost(params,'list_endpoints');
      const epInfo = response.endpoints.map((item:any)=>({model_name:item.model_name,
                                          endpoint_name:item.endpoint_name,
                                        engine:item.engine,
                                        model_path:item.model_s3_path,
                                        instance_type:item.instance_type,}));
      setEndpointsInfo(epInfo);
      setLoadStatus("finished");
    } catch (error) {
      console.log(error);
      setLoadStatus("error");
    }
  };


  useEffect(() => {
    setMaxConversations(localStoredParams?.max_conversations || 10)
    setLocalStoredParams({
      ...localStoredParams,
      system_role_prompt:
        localStoredParams?.system_role_prompt === undefined || localStoredParams?.system_role_prompt === ''
          ? defaultModelParams.system_role_prompt
          : localStoredParams?.system_role_prompt,
      use_stream:
          localStoredParams?.use_stream === undefined
            ? defaultModelParams.use_stream
            : localStoredParams?.use_stream,
      
    });
  }, []);

  // console.log('modelParams:',modelParams);

  return (
    <ExpandableSection headerText={t("addtional_settings")} variant="footer" defaultExpanded={true}>
      <ColumnLayout borders="vertical" columns={3} variant="text-grid">
      <FormField label={t("endpoint_name")} errorText={!endpointName?"select model first":""}>
          <Select
          
           statusType={loadStatus}
           onLoadItems={handleLoadItems}
            selectedOption={epselectedOption}
            onChange={({ detail }) => {
              setepSelectedOption(detail.selectedOption);
              setEndpointName(detail.selectedOption.value);

              setModelName(detail.selectedOption.tags&&detail.selectedOption.tags[1]);
            }}
            options={endpointsInfo.map( (item) => ({label:item.endpoint_name,
              value:item.endpoint_name,
              tags:[item.model_path.startsWith("s3://")?'Finetuned':'Original', 
                item.model_name,item.instance_type,item.engine]
            }))}
            selectedAriaLabel="Selected"
          />
        </FormField>
        {/* <FormField label={t("model_name")}>
          <Select
            selectedOption={{label:epselectedOption.tags&&epselectedOption.tags[0],value:epselectedOption.tags&&epselectedOption.tags[1]}}
            disabled
            options={[{label:epselectedOption.tags&&epselectedOption.tags[0],value:epselectedOption.tags&&epselectedOption.tags[1]}]}
            selectedAriaLabel="Selected"
          />
        </FormField> */}
        
        <FormField label={t("max_tokens")}>
          <Input
            onChange={({ detail }) => {
              settokenSize(detail.value);
              setModelParams((prev:ModelParamProps) => ({
                ...prev,
                max_tokens: parseInt(detail.value),
              }));
              setLocalStoredParams({
                ...localStoredParams,
                max_tokens: parseInt(detail.value),
              });
            }}
            value={tokenSize}
            inputMode="numeric"
          />
        </FormField>
        <FormField label={t("temperature")}>
          <Input
            onChange={({ detail }) => {
              setTempValue(detail.value);
              setModelParams((prev:ModelParamProps) => ({
                ...prev,
                temperature: parseFloat(detail.value),
              }));
              setLocalStoredParams({
                ...localStoredParams,
                temperature: parseFloat(detail.value),
              });
            }}
            value={temperatureValue}
            inputMode="decimal"
          />
        </FormField>
        <FormField label={'top_p'}>
          <Input
            onChange={({ detail }) => {
              setToppValue(detail.value);
              setModelParams((prev:ModelParamProps) => ({
                ...prev,
                top_p: parseFloat(detail.value),
              }));
              setLocalStoredParams({
                ...localStoredParams,
                top_p: parseFloat(detail.value),
              });
            }}
            value={toppValue}
            inputMode="decimal"
          />
        </FormField>
        <FormField label={t("max_conversations")}>
          <Input
            onChange={({ detail }) => {
              setMaxConversations(detail.value)
              setLocalStoredParams({
                ...localStoredParams,
                max_conversations: parseInt(detail.value),
              });
            }}
            value={maxConversations}
            inputMode="numeric"
          />
        </FormField>
        <FormField label={t("system_role_prompt")}>
          <Input
            onChange={({ detail }) => {
              setSystemRolePromptValue(detail.value);
              setModelParams((prev:ModelParamProps) => ({
                ...prev,
                system_role_prompt: detail.value,
              }));
              setLocalStoredParams({
                ...localStoredParams,
                system_role_prompt: detail.value,
              });
            }}
            value={systemRolePromptValue}
          />
        </FormField>
        <FormField label={t("cust_chat_template")}
        description={t("cust_chat_template_desc")}>
          <Textarea
            rows={1}
            onChange={({ detail }) => {
              setChatTemplate(detail.value);
              setModelParams((prev:ModelParamProps) => ({
                ...prev,
                chat_template: detail.value,
              }));
              setLocalStoredParams({
                ...localStoredParams,
                chat_template: detail.value,
              });
            }}
            value={chatTemplate}
          />
        </FormField>
      </ColumnLayout>
    </ExpandableSection>
  );
};

const ImageUploadComp = ({ setLocalStoredMsgItems,files,setFiles }:
          {setLocalStoredMsgItems:any,files:File[],setFiles:any}) => {
  const { t } = useTranslation();
  const { setMsgItems, msgItems, setStopFlag, setBase64Images} = useChatData();
  const [uploadErrtxt, setUploadErr] = useState();
  const [uploadComplete, setUploadComplete] = useState(false);
  const [helperMsg, setHelperMsg] = useState('');
  const handleImageUpload = (imageFiles: File[]) => {
 
        setStopFlag(false);
        const msgid = `image-${generateId()}`;


        const images_base64 = imageFiles.map(async (file) => {
          const reader = new FileReader();
          const base64Data = await new Promise((resolve, reject) => {
            reader.onload = () => {
              if (typeof reader.result === 'string') {
                  resolve((reader.result as string).split(',')[1]);
              } else {
                  console.error('Expected a string, but got ArrayBuffer');
              }
          };
            reader.onerror = reject;
            reader.readAsDataURL(file);
          });
          return base64Data;
        });
        //取出images_base64里的数据
        Promise.all(images_base64).then((base64Data) => {
          // console.log('base64Data:',base64Data);
          setBase64Images(base64Data);
        });

        // setMsgItems(
        //   (prev:any) => [
        //     ...prev,
        //     {
        //       id: msgid,
        //       who: username,
        //       text: 'images',
        //       images: imageFiles,
        //     },
        //   ] //创建一个新的item
        // );
        // // console.log('msgItems:',msgItems);
        // setLocalStoredMsgItems([
        //   ...msgItems,
        //   {
        //     id: msgid,
        //     who: username,
        //     text: 'images',
        //   },
        // ]);
        setUploadComplete(true);

  }

  return (
    <SpaceBetween size="s">
      <FileUpload
        onChange={({ detail }:{detail:any}) => {
          setHelperMsg("");
          setFiles(detail.value);
          setUploadErr(undefined);
          setUploadComplete(false);
          // setImg2txtUrl([]);
          setStopFlag(true);
          handleImageUpload(detail.value);
        }}
        multiple
        value={files}
        accept=".png,.jpg,.jpeg"
        constraintText={helperMsg}
        showFileLastModified
        showFileSize
        showFileThumbnail
        tokenLimit={3}
        errorText={uploadErrtxt}
        i18nStrings={{
          uploadButtonText: (e) =>
            e ? t('image') : t('image'),
          dropzoneText: (e) =>
            e ? "Drop files to upload" : "Drop file to upload",
          removeFileAriaLabel: (e) => `Remove file ${e + 1}`,
          limitShowFewer: "Show fewer files",
          limitShowMore: "Show more files",
          errorIconAriaLabel: "Error",
        }}
      />
    </SpaceBetween>
  )
}


const PromptPanel = ({ sendMessage }:{sendMessage:({id,messages,params}:MessageDataProp)=>void}) => {
  const { t } = useTranslation();
  const [promptValue, setPromptValue] = useState("");
  const {
    modelParams,
    msgItems,
    setMsgItems,
    setLoading,
    setModelParams,
    conversations,
    setConversations,
    stopFlag,
    setStopFlag,
    newChatLoading, 
    setNewChatLoading,
    modelName,
    endpointName,
    base64Images,
    setBase64Images
  } = useChatData();

  const [localStoredParams, setLocalStoredParams] = useLocalStorage<Record<string, any>|null>(
    params_local_storage_key + username,
    null
  );

  const [localStoredMsgItems, setLocalStoredMsgItems] = useLocalStorage<Record<string, any>|null>(
    params_local_storage_key + '-msgitems-'+endpointName,
    []
  );

  const [files, setFiles] = useState([]);

  const [useStreamChecked, setUseStreamChecked] = useState(
    localStoredParams?.use_stream !== undefined
      ? localStoredParams?.use_stream
      : defaultModelParams.use_stream
  );


  useEffect(() => {
    setModelParams({
      ...localStoredParams,
      max_tokens:
        localStoredParams?.max_tokens || defaultModelParams.max_tokens,
      temperature:
        localStoredParams?.temperature || defaultModelParams.temperature,
      top_p:localStoredParams?.top_p || defaultModelParams.top_p,
      chat_template: localStoredParams?.chat_template || defaultModelParams.chat_template,
      use_stream:
          localStoredParams?.use_stream !== undefined
            ? localStoredParams?.use_stream
            : defaultModelParams.use_stream,
      model_name: modelName,
      system_role_prompt:
        localStoredParams?.system_role_prompt ||
        defaultModelParams.system_role_prompt,

      feedback:null,
    });
  }, [endpointName]);


  // const [autoSuggest, setAutoSuggest] = useState(false);
  const onSubmit = (values:string) => {
    setStopFlag(true);
    const prompt = values.trimEnd();
    if (prompt === "") {
      setStopFlag(false);
      return;
    }
    const respid = generateUniqueId();
    setMsgItems((prev:MsgItemProps[]) => [
      ...prev,
      { id: respid, who: username, text: prompt ,images:files},
    ]);

    //save the messages to localstorage
    console.log('msgItems:',msgItems);
    setLocalStoredMsgItems([
      ...msgItems,
      { id: respid, who: username, text: prompt },
    ])

    //add base64 data in message
    const imageMessage = base64Images.map((base64Data:string) => {
      return {
        type: "image_url",
        image_url: {url:`data:image/jpeg;base64,${base64Data}`},
      };
    });

    const inputMessage = base64Images.length ? 
      { role: "user", content: [{"type": "text",text:prompt}, ...imageMessage] } :
      { role: "user", content: prompt };

    setConversations((prev:MsgItemProps[]) => [...prev, inputMessage]);

    const messages = [...conversations, inputMessage];
    setLoading(true);
    const params = {...modelParams}
    sendMessage({ id: respid, messages: messages, params: params });
    console.log("modelParams:", params);
    console.log("messages:", messages);
    setPromptValue("");
    setFiles([]);
    setBase64Images([]);
  };

  return (
    <Container footer={<ExpandableSettingPanel />}>
      <FormField
        stretch={true}
      >
      <SpaceBetween size="s">

      <Grid gridDefinition={[{ colspan: 9 }, { colspan: 3 }]}>
          
          <Textarea
            value={promptValue}
            disabled={stopFlag || newChatLoading}
            onChange={(event) => setPromptValue(event.detail.value)}
            onKeyDown={(event) => {
              if (event.detail.key === "Enter" && !event.detail.ctrlKey) {
                onSubmit(promptValue);
              }
            }}
            placeholder="Enter to send"
            autoFocus
            rows={1}
          />
          
          
          <SpaceBetween size="xs" direction="horizontal">
            <ImageUploadComp 
              setLocalStoredMsgItems={setLocalStoredMsgItems} 
              files = {files}
              setFiles = {setFiles}
             />
            <Button
              variant="primary"
              loading={stopFlag&&!newChatLoading}
              disabled={newChatLoading || !endpointName}
              onClick={(event) => onSubmit(promptValue)}
            >
              {t("send")}
            </Button>
            <Button
              loading={newChatLoading}
              iconName="remove" variant="icon"
              onClick={() => {
                setNewChatLoading(false);
                setFiles([]);
                setConversations([]);
                setMsgItems([]);
                setLocalStoredMsgItems([]);
                setLoading(false);
              }}
            >
              {t("new_chat")}
            </Button>
          </SpaceBetween>
      </Grid>
      <SpaceBetween size="xl" direction="horizontal">
      <FormField >
              <Toggle
                onChange={({ detail }) => {
                  setUseStreamChecked(detail.checked);
                  setModelParams((prev:MsgItemProps[]) => ({
                    ...prev,
                    use_stream: detail.checked,
                  }));
                  setLocalStoredParams({
                    ...localStoredParams,
                    use_stream: detail.checked,
                  });
                }}
                checked={useStreamChecked}
              >{t("use_stream")}</Toggle>
            </FormField>
          </SpaceBetween>
      </SpaceBetween>
      
      </FormField>
    </Container>
  );
};
export default PromptPanel;
