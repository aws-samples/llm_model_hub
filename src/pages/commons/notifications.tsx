// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useId, useState } from 'react';
import Flashbar, { FlashbarProps } from '@cloudscape-design/components/flashbar';
import { useDisclaimerFlashbarItem } from './disclaimer-flashbar-item';


export interface notificationItemProps {
  status: FlashbarProps.Type;
  content: string;
}


function useNotifications(showSuccessNotification = false, data : notificationItemProps) {
  // console.log("useNotifications:",showSuccessNotification,data)
  const successId = useId();
  const [successDismissed, dismissSuccess] = useState(false);
  // const [disclaimerDismissed, dismissDisclaimer] = useState(false);

  // const disclaimerItem = useDisclaimerFlashbarItem(() => dismissDisclaimer(true));

  const notifications: Array<FlashbarProps.MessageDefinition> = [];

  // if (disclaimerItem && !disclaimerDismissed) {
  //   notifications.push(disclaimerItem);
  // }

  if (showSuccessNotification && !successDismissed) {
    notifications.push({
      type: data.status,
      content: data.content,
      statusIconAriaLabel: data.status,
      dismissLabel: 'Dismiss message',
      dismissible: true,
      onDismiss: () => dismissSuccess(true),
      id: successId,
    });
  }

  return notifications;
}

export interface NotificationsProps {
  successNotification?: boolean;
  data:notificationItemProps;
}

export function Notifications({ successNotification,data }: NotificationsProps) {
  
  const notifications = useNotifications(successNotification,data);
  // console.log(notifications);
  return <Flashbar items={notifications} />;
}
