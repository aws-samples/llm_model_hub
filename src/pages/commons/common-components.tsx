// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { forwardRef,createContext ,useContext} from 'react';
import { AppLayout, AppLayoutProps, Badge, Box, Button, SpaceBetween } from '@cloudscape-design/components';

import { I18nProvider } from '@cloudscape-design/components/i18n';
import enMessages from '@cloudscape-design/components/i18n/messages/all.en.json';

interface settingCtxProps {
  modelSettingVisible:boolean
  setModelSettingVisible:(value:boolean)=>void
}

const settingCtx = createContext<settingCtxProps|{}>({});
export const useSettingCtx = ()=>{
  return useContext(settingCtx);
}


// backward compatibility
export * from './index';
export const params_local_storage_key = 'model_hub_params_local_storage_key';
export const TableNoMatchState = ({ onClearFilter }: { onClearFilter: () => void }) => (
  <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
    <SpaceBetween size="xxs">
      <div>
        <b>No matches</b>
        <Box variant="p" color="inherit">
          We can't find a match.
        </Box>
      </div>
      <Button onClick={onClearFilter}>Clear filter</Button>
    </SpaceBetween>
  </Box>
);

export const TableEmptyState = ({ resourceName }: { resourceName: string }) => (
  <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
    <SpaceBetween size="xxs">
      <div>
        <b>No {resourceName.toLowerCase()}s</b>
        <Box variant="p" color="inherit">
          No {resourceName.toLowerCase()}s associated with this resource.
        </Box>
      </div>
      <Button>Create {resourceName.toLowerCase()}</Button>
    </SpaceBetween>
  </Box>
);

export const CustomAppLayout = forwardRef<AppLayoutProps.Ref, AppLayoutProps>((props, ref) => {
  return (
    <I18nProvider locale="en" messages={[enMessages]}>
      <AppLayout ref={ref} {...props} />
    </I18nProvider>
  );
});
