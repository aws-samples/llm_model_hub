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
import { useTranslation } from 'react-i18next';

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
  const { t } = useTranslation();
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
          content: `${t('cluster_delete_initiated')}: "${cluster.cluster_name}"`,
          dismissible: true,
          dismissLabel: 'Dismiss',
          onDismiss: () => setNotificationItems((items: any) =>
            items.filter((item: any) => item.id !== `delete-${cluster.cluster_id}`)
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
          content: `${t('cluster_delete_failed')}: ${error}`,
          dismissible: true,
          dismissLabel: 'Dismiss',
          onDismiss: () => setNotificationItems((items: any) =>
            items.filter((item: any) => item.id !== `delete-error-${cluster.cluster_id}`)
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
      header={t('delete_cluster')}
      closeAriaLabel="Close modal"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => setVisible(false)}>
              {t('cancel')}
            </Button>
            <Button
              variant="primary"
              onClick={handleDelete}
              loading={deleting}
            >
              {t('delete')}
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        <Box>
          {t('confirm_delete_cluster')}{' '}
          <strong>{cluster?.cluster_name}</strong>?
        </Box>
        <Alert type="warning">
          {t('delete_cluster_warning')}
        </Alert>
        <Checkbox
          checked={deleteVpc}
          onChange={({ detail }) => setDeleteVpc(detail.checked)}
        >
          {t('delete_vpc_resources')}
        </Checkbox>
      </SpaceBetween>
    </Modal>
  );
}
