// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useState, createContext,useContext} from 'react';
import { useId } from './use-id';
import { useDisclaimerFlashbarItem } from './disclaimer-flashbar-item';
import { Flashbar } from '@cloudscape-design/components';

const notificationCtx = createContext();

export function SimpleNotifications({children}){
  const [notificationitems,setNotificationItems] = useState([]);
  return  <notificationCtx.Provider value={{notificationitems,setNotificationItems}}>
    {children}
  </notificationCtx.Provider>
}

export const useSimpleNotifications = () => {
  return useContext(notificationCtx);
};

export function useNotifications(successNotification) {
  const successId = useId();
  const [successDismissed, dismissSuccess] = useState(false);
  const [disclaimerDismissed, dismissDisclaimer] = useState(true);

  const disclaimerItem = useDisclaimerFlashbarItem(() => dismissDisclaimer(false));

  const notifications = [];

  if (disclaimerItem && !disclaimerDismissed) {
    notifications.push(disclaimerItem);
  }

  if (successNotification & !successDismissed) {
    notifications.push({
      type: 'success',
      content: 'Resource created successfully',
      statusIconAriaLabel: 'success',
      dismissLabel: 'Dismiss message',
      dismissible: true,
      onDismiss: () => dismissSuccess(true),
      id: successId,
    });
  }

  return notifications;
}
