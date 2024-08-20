// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import { Button, Header, HeaderProps, SpaceBetween } from '@cloudscape-design/components';

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
  onDeploy?:()=>void;
}

export function FullPageHeader({
  title = 'Jobs',
  createButtonText = 'Create Job',
  extraActions = null,
  selectedItemsCount,
  selectedItems,
  setDisplayNotify,
  setNotificationData,
  onInfoLinkClick,
  onDelete,
  onRefresh,
  onDeploy,
  ...props
}: FullPageHeaderProps) {
  const isOnlyOneSelected = selectedItemsCount === 1;
  const selectedItem = selectedItems&&selectedItems[0];
  return (
    <Header
      variant="awsui-h1-sticky"
      // info={onInfoLinkClick && <InfoLink onFollow={onInfoLinkClick} />}
      actions={
        <SpaceBetween size="xs" direction="horizontal">
          {extraActions}
          <Button data-testid="header-btn-refresh" iconName="refresh"  onClick={onRefresh}>
            Refresh
          </Button>
          <Button data-testid="header-btn-deploy" onClick={onDeploy} disabled={!isOnlyOneSelected || selectedItem?.job_status !== 'SUCCESS' }>
            Deploy
          </Button>
          <Button data-testid="header-btn-edit" disabled={!isOnlyOneSelected}>
            Edit
          </Button>
          <Button data-testid="header-btn-delete" disabled={selectedItemsCount === 0} onClick={onDelete}>
            Delete
          </Button>
          <Button data-testid="header-btn-create" variant="primary" href='/jobs/createjob'>
            {createButtonText}
          </Button>
        </SpaceBetween>
      }
      {...props}
    >
      {title}
    </Header>
  );
}
