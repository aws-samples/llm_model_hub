// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useState } from 'react';
import {
  Box,
  Button,
  Checkbox,
  Modal,
  SpaceBetween,
  Alert,
} from '@cloudscape-design/components';
import { deleteCluster } from './hooks';
import { useSimpleNotifications } from '../commons/use-notifications';

interface DeleteClusterModalProps {
  visible: boolean;
  setVisible: (visible: boolean) => void;
  selectedItems: any[];
  onRefresh: () => void;
}

export function DeleteClusterModal({
  visible,
  setVisible,
  selectedItems,
  onRefresh,
}: DeleteClusterModalProps) {
  const [deleting, setDeleting] = useState(false);
  const [deleteVpc, setDeleteVpc] = useState(false);
  const { setNotificationItems } = useSimpleNotifications();
  const cluster = selectedItems[0];

  const handleDelete = async () => {
    if (!cluster) return;

    setDeleting(true);
    try {
      await deleteCluster(cluster.cluster_id, deleteVpc);
      setNotificationItems((items: any) => [
        ...items,
        {
          type: 'success',
          content: `Cluster "${cluster.cluster_name}" deletion initiated`,
          dismissible: true,
          dismissLabel: 'Dismiss',
          onDismiss: () => setNotificationItems((items: any) =>
            items.filter((item: any) => item.content !== `Cluster "${cluster.cluster_name}" deletion initiated`)
          ),
          id: `delete-${cluster.cluster_id}`,
        },
      ]);
      setVisible(false);
      onRefresh();
    } catch (error) {
      setNotificationItems((items: any) => [
        ...items,
        {
          type: 'error',
          content: `Failed to delete cluster: ${error}`,
          dismissible: true,
          dismissLabel: 'Dismiss',
          onDismiss: () => setNotificationItems((items: any) =>
            items.filter((item: any) => item.content !== `Failed to delete cluster: ${error}`)
          ),
          id: `delete-error-${cluster.cluster_id}`,
        },
      ]);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Modal
      visible={visible}
      onDismiss={() => setVisible(false)}
      header="Delete cluster"
      closeAriaLabel="Close modal"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => setVisible(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handleDelete}
              loading={deleting}
            >
              Delete
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        <Box>
          Are you sure you want to delete cluster{' '}
          <strong>{cluster?.cluster_name}</strong>?
        </Box>
        <Alert type="warning">
          This action will delete the HyperPod cluster and associated resources.
          This action cannot be undone.
        </Alert>
        <Checkbox
          checked={deleteVpc}
          onChange={({ detail }) => setDeleteVpc(detail.checked)}
        >
          Also delete associated VPC resources
        </Checkbox>
      </SpaceBetween>
    </Modal>
  );
}
