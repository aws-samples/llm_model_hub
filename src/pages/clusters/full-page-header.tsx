// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import { Button, Header, SpaceBetween } from '@cloudscape-design/components';
import { useNavigate } from 'react-router-dom';

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
          Info
        </Button>
      )}
      actions={
        <SpaceBetween size="xs" direction="horizontal">
          <Button iconName="refresh" onClick={onRefresh} />
          <Button
            disabled={!canDelete}
            onClick={onDelete}
          >
            Delete
          </Button>
          <Button
            variant="primary"
            onClick={() => navigate('/clusters/create')}
          >
            Create Cluster
          </Button>
        </SpaceBetween>
      }
    >
      HyperPod Clusters
    </Header>
  );
}
