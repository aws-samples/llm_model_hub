// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React ,{useState} from 'react';
import { Button, Modal, Box,  SpaceBetween, } from '@cloudscape-design/components';
import { remotePost } from '../../common/api-gateway';
import { useTranslation } from "react-i18next";
import {useSimpleNotifications} from '../commons/use-notifications';

interface PageHeaderProps {
  extraActions?: React.ReactNode;
  selectedItems:ReadonlyArray<any>,
  visible: boolean;
  setVisible: (value: boolean) => void;
  setDisplayNotify: (value: boolean) => void;
  setNotificationData: (value: any) => void;
  onDelete?: () => void;
  onRefresh?: () => void;
}


export const DeleteModelModal = ({
    extraActions = null,
    selectedItems,
    visible,
    setVisible,
    setDisplayNotify,
    setNotificationData,
    onRefresh,
    ...props
  }: PageHeaderProps) => {
    const { t } = useTranslation();
    const endpoint_name = selectedItems[0].endpoint_name
    const { setNotificationItems } = useSimpleNotifications();
    const onDeloyConfirm =()=>{
        const msgid = `msg-${Math.random().toString(8)}`;
        const fromData = {endpoint_name:endpoint_name}
        remotePost(fromData, 'delete_endpoint').
        then(res => {
            if (res.response.result) {
            //   console.log(res.response)
              setVisible(false);
              // setDisplayNotify(true);
              // setNotificationData({ status: 'success', content: `Delete Endpoint :${endpoint_name} Success` });
              setNotificationItems((item:any) => [
                ...item,
                {
                  type: "success",
                  content: `Delete Endpoint :${endpoint_name} Success`,
                  dismissible: true,
                  dismissLabel: "Dismiss message",
                  onDismiss: () =>
                    setNotificationItems((items:any) =>
                      items.filter((item:any) => item.id !== msgid)
                    ),
                  id: msgid,
                },
              ]);
              onRefresh?.();
            }else{
                setVisible(false);
                // setDisplayNotify(true);
                // setNotificationData({ status: 'error', content: `Delete Endpoint :${endpoint_name} Failed` });
                setNotificationItems((item:any) => [
                  ...item,
                  {
                    type: "error",
                    content: `Delete Endpoint :${endpoint_name} Failed`,
                    dismissible: true,
                    dismissLabel: "Dismiss message",
                    onDismiss: () =>
                      setNotificationItems((items:any) =>
                        items.filter((item:any) => item.id !== msgid)
                      ),
                    id: msgid,
                  },
                ]);
                onRefresh?.();
            }
        
        })
        .catch(err => {
          // setDisplayNotify(true);
          setVisible(false);
          // setNotificationData({ status: 'error', content: `Delete Endpoint failed` });
          setNotificationItems((item:any) => [
            ...item,
            {
              type: "error",
              content: `Delete Endpoint :${endpoint_name} Failed`,
              dismissible: true,
              dismissLabel: "Dismiss message",
              onDismiss: () =>
                setNotificationItems((items:any) =>
                  items.filter((item:any) => item.id !== msgid)
                ),
              id: msgid,
            },
          ]);
        })
    }
    return (
      <Modal
        onDismiss={() => setVisible(false)}
        visible={visible}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={()=> setVisible(false)}>Cancel</Button>
              <Button variant="primary" onClick={onDeloyConfirm}>Confirm</Button>
            </SpaceBetween>
          </Box>
        }
        header="Delete endpoint"
      >
        {`Confirm to delete endpoint:${endpoint_name}` }
      </Modal>
    );
  }