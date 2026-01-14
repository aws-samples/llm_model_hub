// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import { Button, Header, SpaceBetween } from '@cloudscape-design/components';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

interface FullPageHeaderProps {
  selectedItemsCount: number;
  selectedItems: any[];
  counter?: string;
  onDelete: () => void;
  onRefresh: () => void;
  onInfoLinkClick?: () => void;
}

export function FullPageHeader({
  selectedItemsCount,
  selectedItems,
  counter,
  onDelete,
  onRefresh,
  onInfoLinkClick,
}: FullPageHeaderProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const isOnlyOneSelected = selectedItemsCount === 1;
  const selectedCluster = selectedItems[0];
  const canDelete = isOnlyOneSelected &&
    selectedCluster?.cluster_status !== 'DELETING' &&
    selectedCluster?.cluster_status !== 'CREATING';

  return (
    <Header
      variant="awsui-h1-sticky"
      counter={counter}
      info={onInfoLinkClick && (
        <Button variant="link" onClick={onInfoLinkClick}>
          {t('info')}
        </Button>
      )}
      actions={
        <SpaceBetween size="xs" direction="horizontal">
          <Button iconName="refresh" onClick={onRefresh} />
          <Button
            disabled={!canDelete}
            onClick={onDelete}
          >
            {t('delete')}
          </Button>
          <Button
            variant="primary"
            onClick={() => navigate('/clusters/create')}
          >
            {t('create_cluster')}
          </Button>
        </SpaceBetween>
      }
    >
      {t('hyperpod_clusters')}
    </Header>
  );
}
