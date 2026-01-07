// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import { Button, Header, HeaderProps, SpaceBetween } from '@cloudscape-design/components';
import { useTranslation } from 'react-i18next';

interface FullPageHeaderProps extends HeaderProps {
  title?: string;
  createButtonText?: string;
  extraActions?: React.ReactNode;
  selectedItemsCount: number;
  selectedItems:ReadonlyArray<any>,
  setDisplayNotify: (value: boolean) => void;
  setNotificationData: (value: any) => void;
  onInfoLinkClick?: () => void;
  onDelete?: () => void;
  onRefresh?: () => void;
  onDeploy?: () => void;
  onViewCode?: () => void;
}
// || selectedItems[0].endpoint_status !== 'INSERVICE'
export function FullPageHeader({
  title,
  createButtonText,
  extraActions = null,
  selectedItemsCount,
  selectedItems,
  setDisplayNotify,
  setNotificationData,
  onInfoLinkClick,
  onDelete,
  onRefresh,
  onDeploy,
  onViewCode,
  ...props
}: FullPageHeaderProps) {
  const { t } = useTranslation();
  const displayTitle = title || t('endpoints');
  const displayButtonText = createButtonText || t('chat');
  // console.log("selectedItems",selectedItems)
  return (
    <Header
      variant="awsui-h1-sticky"

      actions={
        <SpaceBetween size="xs" direction="horizontal">
          {extraActions}
          <Button data-testid="header-btn-refresh" iconName="refresh"  onClick={onRefresh}>
            {t('refresh')}
          </Button>
          <Button data-testid="header-btn-delete" disabled={selectedItemsCount === 0 } onClick={onDelete}>  
            {t('delete')}
          </Button>
          <Button data-testid="header-btn-create" onClick={onDeploy}>  
           {t('create')}
          </Button>
          <Button data-testid="header-btn-chat" variant="primary" disabled={selectedItemsCount === 0 || selectedItems&&selectedItems[0]?.endpoint_status !== 'INSERVICE' } href={`/chat/${selectedItems&&selectedItems[0]?.endpoint_name}`}>
            {displayButtonText}
          </Button>
          <Button data-testid="header-btn-viewcode" disabled={selectedItemsCount === 0 || selectedItems&&selectedItems[0]?.endpoint_status !== 'INSERVICE' } onClick={onViewCode}>
          {t('viewcode')}
          </Button>
        </SpaceBetween>
      }
      {...props}
    >
      {displayTitle}
    </Header>
  );
}
