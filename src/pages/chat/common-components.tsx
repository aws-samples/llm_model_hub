// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, {createContext, useContext} from 'react';
import { BreadcrumbGroup, HelpPanel, Icon, Box,Link } from '@cloudscape-design/components';
import { ExternalLinkItem } from '../commons/common-components';
// import langString from "../../common/language_string";
import i18n from '../../common/i18n';


export const ChatDataCtx = createContext<any>({});
export const useChatData = ()=>{
  return useContext(ChatDataCtx)
}

export const params_local_storage_key = "chat-params-prompt-panel-";


export function generateUniqueId() {
  const timestamp = Date.now();
  const randomNumber = Math.random();
  const hexadecimalString = randomNumber.toString(16).slice(3);

  return `id-${timestamp}-${hexadecimalString}`;
}


export const LabelVals =({label,value}:{label:string,value:string})=>{
  return(
    <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box variant="awsui-value-large">{value}</Box>
  </div>
  )
}

const toolsFooter = (
  <>
    <h3>
      Learn more{' '}
      <span role="img" aria-label="Icon external Link">
        <Icon name="external" />
      </span>
    </h3>
    <ul>
      <li>
        <ExternalLinkItem
          href="#"
          text=""
        />
      </li>
    </ul>
  </>
);
export const ToolsContent = () => (
  <HelpPanel footer={toolsFooter} header={<h2>App</h2>}>
    <p>
     ....
    </p>
  </HelpPanel>
);
