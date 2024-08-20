// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState, useRef, memo } from "react";
import {
  Container,
  Header,
  SpaceBetween,
  Button,
} from "@cloudscape-design/components";
import SyntaxHighlighter from "react-syntax-highlighter";
import { a11yDark } from "react-syntax-highlighter/dist/esm/styles/hljs";
// import { CopyBlock,a11yDark } from "react-code-blocks";
import { useChatData, generateUniqueId } from "./common-components";
import { useTranslation } from "react-i18next";
import botlogo from "../../resources/Res_Amazon-SageMaker_Model_48_Light.svg";
import userlogo from "../../resources/icons8-user-96.png"
import { useLocalStorage } from '../commons/use-local-storage';
import { remotePost,API_ENDPOINT,fetchPost} from "../../common/api-gateway";
// import useWebSocket from "react-use-websocket";
import PromptPanel from "./prompt-panel";
import { params_local_storage_key } from "./common-components";
import ReactMarkdown from "react-markdown";
import gfm from "remark-gfm";

import {
  Box,
  Stack,
  Avatar,
  List,
  ListItem,
  Grid,
} from "@mui/material";
import { grey } from "@mui/material/colors";

const BOTNAME = "assistant";
const MAX_CONVERSATIONS = 6;



const MarkdownToHtml = ({ text }: { text: string }) => {
  return (
    <ReactMarkdown
      children={text}
      remarkPlugins={[gfm]}
      components={{
        code({ node, inline, className, children, ...props }: any) {
          const match = /language-(\w+)/.exec(className || "");
          return !inline && match ? (
            <SyntaxHighlighter
              {...props}
              children={String(children).replace(/\n$/, "")}
              style={a11yDark}
              wrapLongLines
              language={match[1]}
              PreTag="div"
            />
          ) : (
            <code {...props} className={className}>
              {children}
            </code>
          );
        },
        img: (image) => (
          <img
            src={image.src || ""}
            alt={image.alt || ""}
            width={500}
            loading="lazy"
          />
        ),
      }}
    />
  );
};

export interface MsgItemProps {
  who: string;
  text: string;
  images_base64: string[];
  images: File[];
  id: string;
};

const username = 'default'
const sessionId = `web_chat_${username}`

const MsgItem = ({ who, text, images_base64, images, id }: MsgItemProps) => {


  //restore image file from localstorage
  if (images_base64) {

    const imagesObj = images_base64.map((base64Data, key) => {
      const binaryString = window.atob(base64Data); // 将 base64 字符串解码为二进制字符串
      const bytes = new Uint8Array(binaryString.length);

      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      const blob = new Blob([bytes], { type: 'image/png' });
      // Create a new File object from the Blob
      return new File([blob], `image_${key}.png`, { type: 'image/png' });
    });
    return (
      <ListItem >
        {who !== BOTNAME &&
          <Stack direction="row" spacing={2} sx={{ alignItems: "top" }}>
            <Avatar src={userlogo} alt={"User"} />
          </Stack>}
      </ListItem>
    );

  }
  else if (images) {

    return (
      <ListItem >
        {who !== BOTNAME && <Stack direction="row" spacing={2} sx={{ alignItems: "top" }}>
          <Avatar src={userlogo} alt={"User"} />
        </Stack>}
      </ListItem>
    );
  } else {
    let newlines = [];
    if (who === BOTNAME) {
      newlines.push(text);
    } else {
      newlines = [text];
    }
    // console.log(text);

    return who !== BOTNAME ? (
      <ListItem >
        <Stack direction="row" spacing={2} sx={{ alignItems: "top" }}>
          <Avatar src={userlogo} alt={"User"} />
          <Grid container spacing={0.1}>
            <TextItem sx={{ bgcolor: "#f2fcf3", borderColor: "#037f0c" }}>
              <MarkdownToHtml text={newlines.join(" ")} />
            </TextItem>
          </Grid>
        </Stack>
      </ListItem>
    ) : (
      <ListItem >
        <Stack direction="row" spacing={2} sx={{ alignItems: "top" }}>
          <Avatar src={botlogo} alt={"AIBot"} />
          <TextItem>
            <MarkdownToHtml text={newlines.join(" ")} />
          </TextItem>
        </Stack>
      </ListItem>
    );
  }
};

const TextItem = (props: any) => {
  const { sx, ...other } = props;
  // console.log(other);
  return (
    <Box
      sx={{
        pr: 1,
        pl: 1,
        m: 1,
        whiteSpace: "normal",
        bgcolor: "#f2f8fd",
        color: grey[800],
        border: "2px solid",
        borderColor: "#0972d3",
        borderRadius: 2,
        fontSize: "14px",
        minWidth: "40px",
        width: "auto",
        fontWeight: "400",
        ...sx,
      }}
      {...other}
    />
  );
};

const MemoizedMsgItem = memo(MsgItem);

const ChatBox = ({ msgItems, loading }: { msgItems: MsgItemProps[], loading: boolean }) => {
  const [loadingtext, setLoaderTxt] = useState("Loading.");
  const intervalRef = useRef<number | null>(null);
  function handleStartTick() {

    let textContent = "";
    const intervalId = setInterval(() => {
      setLoaderTxt((v) => v + ".");
      textContent += ".";
      if (textContent.length > 6) {
        setLoaderTxt('Loading.');
        textContent = "";
      }
    }, 500);
    intervalRef.current = intervalId as unknown as number;
  }

  function handleStopClick() {
    const intervalId = intervalRef.current;
    if (intervalId) clearInterval(intervalId);
  }
  useEffect(() => {
    if (loading) {
      setLoaderTxt("Loading.");
      handleStartTick();
    } else {
      setLoaderTxt("");
      handleStopClick();
    }
  }, [loading]);

  const scrollRef = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [msgItems.length]);
  const items = msgItems.map((msg: MsgItemProps) => (
    <MemoizedMsgItem
      key={generateUniqueId()}
      who={msg.who}
      text={msg.text}
      images={msg.images}
      images_base64={msg.images_base64}
      id={msg.id}
    />
  ));

  return (
    <Box sx={{ minWidth: 300, minHeight: 400 }}>
      <List
        sx={{
          position: "relative",
          overflow: "auto",
        }}
      >
        {items}
        {loading && (
          <MemoizedMsgItem key={generateUniqueId()} who={BOTNAME} text={loadingtext} images={[]} images_base64={[]} id={generateUniqueId()} />
        )}
        <ListItem ref={scrollRef} />
      </List>
    </Box>
  );
};

export interface MessageDataProp {
  id: string
  messages: Record<string, any>[],
  params: Record<string, any>
}

function extractJsonFromString(str:string) {
  if (str ==='data  [DONE]') return `[DONE]`
  // 使用正则表达式匹配 JSON 部分
  const match = str.match(/\{.*\}/);
  
  if (match) {
    try {
      // 尝试解析匹配到的 JSON 字符串
      const jsonObj = JSON.parse(match[0]);
      return jsonObj;
    } catch (error) {
      console.error("Error parsing JSON:", error);
      return `[DONE]`;
    }
  } else {
    console.log("No JSON found in the string");
    return `[DONE]`;
  }
}


const ConversationsPanel = () => {
  const { t } = useTranslation();
  const didUnmount = useRef(false);
  const {
    msgItems,
    setMsgItems,
    loading,
    setLoading,
    conversations,
    maxConversations,
    setConversations,
    setStopFlag,
    endpointName,
    setEndpointName,
    setModelName,
    modelName,
    modelParams,
    setNewChatLoading,
  } = useChatData();
  const streamOutput = useRef("");
  useEffect(() => {
    return () => {
      didUnmount.current = true;
    };
  }, []);

  const [localStoredMsgItems, setLocalStoredMsgItems] = useLocalStorage<Record<string, any>|null>(
    params_local_storage_key + '-msgitems-'+endpointName,
    []
  );

  // const [msgItems, setMsgItems] = useState<any>(localStoredMsgItems);


  function sendMessage({ id, messages, params }: MessageDataProp) {
    let newMessages :any[]= [];
    if (messages.length > maxConversations){ //截断
      newMessages = messages.slice(messages.length - maxConversations);
      setConversations(
        (prev:MsgItemProps[]) =>
          prev.slice(conversations.length - MAX_CONVERSATIONS)) 
    }else{
      newMessages = messages;
    }

    const system_message = modelParams.system_role_prompt?{role: "system", content: modelParams.system_role_prompt}:undefined;
    //插入系统消息
    system_message&&newMessages.unshift(system_message);
    const formData = {
      endpoint_name: endpointName,
      model_name: modelName,
      messages: newMessages,
      id: id,
      "params": {
        max_new_tokens: params.max_tokens,
        do_sample: true,
        top_p: params.top_p,
        temperature: params.temperature
      },
      stream:params.use_stream

    }

    if (params.use_stream){
      fetchPost(formData,"chat/completions")
      .then(async (response) => {
        const reader = response.body?.getReader();
        if (!reader) {
            throw new Error('Response body is not readable');
        }
        const decoder = new TextDecoder();
        let isNew = true;
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // 处理完整的数据块
          while (buffer.includes('\n\n')) {
            const index = buffer.indexOf('\n\n');
            const chunk = buffer.slice(0, index);
            buffer = buffer.slice(index + 2);
            // console.log('chunk',chunk);
            // 处理完整的行
            const chunk_obj = extractJsonFromString(chunk)
            // console.log('chunk_obj',chunk_obj);
            if ( chunk_obj !== '[DONE]' && chunk_obj?.choices[0].delta?.role ) continue  //ship first message chunk
            onStreamMessageCallback( {resp: chunk_obj, isNew: isNew })
            isNew = false
          }
        }

      setLoading(false);
      setNewChatLoading(false);
      setStopFlag(false);
        
      }).catch((err) => {
        console.log(err);
        const response= {
          id:id,
          choices:[
            {message:{content:`internal error ${err}`}}
          ]
        }
        onMessageCallback({ resp: response })
      })
    }else{
      remotePost(formData, "chat/completions")
      .then( (resp) => {
          onMessageCallback({ resp: resp.response })
      }).catch((err) => {
        console.log(err);
        const response= {
          id:id,
          choices:[
            {message:{content:`internal error ${err}`}}
          ]
        }
        onMessageCallback({ resp: response })
      })
    }
  }

  const onStreamMessageCallback = ({ resp, isNew}: { resp: any, isNew:boolean}) => {
    setLoading(false);
    setNewChatLoading(false);
    if (resp === "[DONE]") {
      setStopFlag(false);
      setConversations((prev:MsgItemProps[]) => [
        ...prev,
        {
          role: BOTNAME,
          content: streamOutput.current,
        },
      ]);
      setLocalStoredMsgItems([
        ...msgItems,
        { id: resp.id, who: username, text: streamOutput.current },
      ]);

    }else{

      const chunk = resp.choices[0].delta.content??'';
      // console.log(chunk)
      streamOutput.current = streamOutput.current + chunk;
      if (isNew) {
        streamOutput.current = ''
        setMsgItems((prev: MsgItemProps[]) => [
          ...prev,
          {
            id: resp.id,
            who: BOTNAME,
            text: chunk,
          },
        ]);
        streamOutput.current = streamOutput.current + chunk;
      }else{
        setMsgItems((prev: MsgItemProps[]) => [
          ...prev.slice(0, -1),
          {
            id: resp.id,
            who: BOTNAME,
            text: streamOutput.current,
          },
        ]);
      }
    }
  };
  const onMessageCallback = ({ resp, }: { resp: any}) => {
    setLoading(false);
    setNewChatLoading(false);
      setStopFlag(false);
      //创建一个新的item
      streamOutput.current = resp.choices[0].message.content;
      setMsgItems((prev: MsgItemProps[]) => [
        ...prev,
        {
          id: resp.id,
          who: BOTNAME,
          text: streamOutput.current,
        },
      ]);
      setConversations((prev:MsgItemProps[]) => [
        ...prev,
        {
          role: BOTNAME,
          content: streamOutput.current,
        },
      ]);
      setLocalStoredMsgItems([
        ...msgItems,
        { id: resp.id, who: username, text: streamOutput.current },
      ]);
  }



  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">{t("conversations")}</Header>}>
        <ChatBox msgItems={msgItems} loading={loading} />
      </Container>
      <PromptPanel sendMessage={sendMessage}/>
    </SpaceBetween>
  );
};

export default ConversationsPanel;
