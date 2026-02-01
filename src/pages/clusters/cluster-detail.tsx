// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  ColumnLayout,
  Container,
  Header,
  SpaceBetween,
  StatusIndicator,
  Tabs,
  Table,
  Flashbar,
  Spinner,
  CopyToClipboard,
  Modal,
  FormField,
  Input,
  Select,
  Checkbox,
} from '@cloudscape-design/components';
import { CustomAppLayout, Navigation } from '../commons/common-components';
import { Breadcrumbs } from '../commons/breadcrumbs';
import { TopNav } from '../commons/top-nav';
import SpotPriceInfo from '../commons/spot-price-info';
import { getCluster, updateClusterInstanceGroups, listClusterNodes, getClusterSubnets, getInstanceTypeAzs } from './hooks';
import { useSimpleNotifications } from '../commons/use-notifications';
import { useTranslation } from 'react-i18next';
import {instanceTypeOptions} from './create-cluster';

const statusTypeMap: Record<string, 'pending' | 'in-progress' | 'success' | 'error' | 'stopped'> = {
  PENDING: 'pending',
  CREATING: 'in-progress',
  UPDATING: 'in-progress',
  ACTIVE: 'success',
  DELETING: 'in-progress',
  FAILED: 'error',
  DELETED: 'stopped',
};

const statusLabelMap: Record<string, string> = {
  PENDING: 'Pending',
  CREATING: 'Creating',
  UPDATING: 'Updating',
  ACTIVE: 'Active',
  DELETING: 'Deleting',
  FAILED: 'Failed',
  DELETED: 'Deleted',
};

interface InstanceGroup {
  name: string;
  instance_type: string;
  instance_count: number;
  min_instance_count?: number;
  use_spot?: boolean;
  training_plan_arn?: string;
  storage_volume_size?: number;
  enable_instance_stress_check?: boolean;
  enable_instance_connectivity_check?: boolean;
  override_subnet_id?: string;
  override_security_group_ids?: string[];
}

interface SubnetInfo {
  subnet_id: string;
  availability_zone: string;
  availability_zone_id: string;
  cidr_block?: string;
  name?: string;
  is_public?: boolean;
}

interface ClusterNode {
  instance_id: string;
  instance_status: string;
  instance_group_name: string;
  instance_type?: string;
  launch_time?: string;
  is_occupied?: boolean;
  occupied_by?: string;
}

interface ClusterData {
  cluster_id: string;
  cluster_name: string;
  eks_cluster_name: string;
  eks_cluster_arn?: string;
  hyperpod_cluster_arn?: string;
  cluster_status: string;
  vpc_id?: string;
  subnet_ids?: string[];
  instance_groups?: InstanceGroup[];
  cluster_create_time?: string;
  cluster_update_time?: string;
  error_message?: string;
  cluster_config?: {
    eks_config?: {
      kubernetes_version?: string;
    };
    hyperpod_config?: {
      node_recovery?: string;
      enable_autoscaling?: boolean;
      enable_tiered_storage?: boolean;
      tiered_storage_memory_percentage?: number;
    };
    lifecycle_script_s3_uri?: string;
  };
}

// const instanceTypeOptions = [
//   { label: 'ml.c5.large (CPU)', value: 'ml.c5.large' },
//   { label: 'ml.c5.xlarge (CPU)', value: 'ml.c5.xlarge' },
//   { label: 'ml.g5.xlarge (1x A10G)', value: 'ml.g5.xlarge' },
//   { label: 'ml.g5.2xlarge (1x A10G)', value: 'ml.g5.2xlarge' },
//   { label: 'ml.g5.4xlarge (1x A10G)', value: 'ml.g5.4xlarge' },
//   { label: 'ml.g5.8xlarge (1x A10G)', value: 'ml.g5.8xlarge' },
//   { label: 'ml.g5.12xlarge (4x A10G)', value: 'ml.g5.12xlarge' },
//   { label: 'ml.g5.24xlarge (4x A10G)', value: 'ml.g5.24xlarge' },
//   { label: 'ml.g5.48xlarge (8x A10G)', value: 'ml.g5.48xlarge' },
//   { label: 'ml.p4d.24xlarge (8x A100 40GB)', value: 'ml.p4d.24xlarge' },
//   { label: 'ml.p4de.24xlarge (8x A100 80GB)', value: 'ml.p4de.24xlarge' },
//   { label: 'ml.p5.48xlarge (8x H100)', value: 'ml.p5.48xlarge' },
//   { label: 'ml.p5e.48xlarge (8x H200)', value: 'ml.p5e.48xlarge' },
//   { label: 'ml.p5en.48xlarge (8x H200)', value: 'ml.p5en.48xlarge' },
// ];

const emptyInstanceGroup: InstanceGroup = {
  name: '',
  instance_type: 'ml.g5.xlarge',
  instance_count: 1,
  min_instance_count: 0,
  use_spot: false,
  training_plan_arn: '',
  storage_volume_size: 500,
  enable_instance_stress_check: false,
  enable_instance_connectivity_check: false,
  override_subnet_id: '',
  override_security_group_ids: [],
};

// Helper function to extract account ID and region from ARN
function parseArnInfo(arn: string | undefined): { accountId: string; region: string } | null {
  if (!arn) return null;
  // ARN format: arn:aws:service:region:account-id:resource
  const parts = arn.split(':');
  if (parts.length >= 5) {
    return {
      region: parts[3],
      accountId: parts[4],
    };
  }
  return null;
}

// Helper function to get default lifecycle script S3 URI
function getDefaultLifecycleScriptUri(cluster: ClusterData): string {
  const arnInfo = parseArnInfo(cluster.hyperpod_cluster_arn || cluster.eks_cluster_arn);
  if (arnInfo) {
    return `s3://llm-modelhub-hyperpod-${arnInfo.accountId}-${arnInfo.region}/LifecycleScripts/base-config/`;
  }
  return '-';
}

function ClusterDetailContent() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { setNotificationItems } = useSimpleNotifications();
  const [cluster, setCluster] = useState<ClusterData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTabId, setActiveTabId] = useState('overview');

  // Instance Group management state
  const [selectedInstanceGroups, setSelectedInstanceGroups] = useState<InstanceGroup[]>([]);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [editingGroup, setEditingGroup] = useState<InstanceGroup>({ ...emptyInstanceGroup });
  const [savingGroup, setSavingGroup] = useState(false);

  // Cluster Nodes/Instances state
  const [clusterNodes, setClusterNodes] = useState<ClusterNode[]>([]);
  const [nodesLoading, setNodesLoading] = useState(false);
  const [nodesLastUpdated, setNodesLastUpdated] = useState<Date | null>(null);
  const [errorDismissed, setErrorDismissed] = useState(false);

  // Subnet info state for override selection
  const [clusterSubnets, setClusterSubnets] = useState<SubnetInfo[]>([]);
  const [subnetsLoading, setSubnetsLoading] = useState(false);
  const [instanceTypeAzs, setInstanceTypeAzs] = useState<string[]>([]);

  useEffect(() => {
    if (id) {
      loadCluster(id);
      // Reset error dismissed state when viewing a different cluster
      setErrorDismissed(false);
    }
  }, [id]);

  const loadCluster = async (clusterId: string) => {
    setLoading(true);
    try {
      const response = await getCluster(clusterId);
      // API returns { response_id, response: { statusCode, body } } or direct body
      const body = response?.response?.body ?? response?.body ?? response;
      if (body) {
        setCluster(body);
      }
    } catch (error) {
      console.error('Error loading cluster:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = () => {
    if (id) {
      loadCluster(id);
      // Also refresh nodes to update instance status in Instance Groups tab
      loadNodes(id);
    }
  };

  const loadNodes = async (clusterId: string) => {
    setNodesLoading(true);
    try {
      const response = await listClusterNodes(clusterId);
      const nodes = response?.nodes || [];
      setClusterNodes(nodes);
      setNodesLastUpdated(new Date());
    } catch (error) {
      console.error('Error loading cluster nodes:', error);
      setClusterNodes([]);
    } finally {
      setNodesLoading(false);
    }
  };

  const handleRefreshNodes = () => {
    if (id) {
      loadNodes(id);
    }
  };

  const loadSubnets = async (clusterId: string) => {
    setSubnetsLoading(true);
    try {
      const response = await getClusterSubnets(clusterId);
      const body = response?.response?.body ?? response?.body ?? response;
      const subnets = body?.subnets || [];
      setClusterSubnets(subnets);
    } catch (error) {
      console.error('Error loading cluster subnets:', error);
      setClusterSubnets([]);
    } finally {
      setSubnetsLoading(false);
    }
  };

  const loadInstanceTypeAzs = async (instanceType: string) => {
    try {
      const response = await getInstanceTypeAzs(instanceType);
      const azs = response?.response?.available_azs || [];
      setInstanceTypeAzs(azs);
    } catch (error) {
      console.error('Error loading instance type AZs:', error);
      setInstanceTypeAzs([]);
    }
  };

  const handleAddGroup = () => {
    const newGroup = { ...emptyInstanceGroup, name: `worker-group-${(cluster?.instance_groups?.length || 0) + 1}` };
    setEditingGroup(newGroup);
    // Load subnets if not already loaded
    if (id && clusterSubnets.length === 0) {
      loadSubnets(id);
    }
    // Load instance type AZs for the default instance type
    loadInstanceTypeAzs(newGroup.instance_type);
    setShowAddModal(true);
  };

  const handleEditGroup = () => {
    if (selectedInstanceGroups.length === 1) {
      const groupToEdit = { ...selectedInstanceGroups[0] };
      setEditingGroup(groupToEdit);
      // Load subnets if not already loaded
      if (id && clusterSubnets.length === 0) {
        loadSubnets(id);
      }
      // Load instance type AZs for the group's instance type
      loadInstanceTypeAzs(groupToEdit.instance_type);
      setShowEditModal(true);
    }
  };

  const handleDeleteGroup = () => {
    if (selectedInstanceGroups.length > 0) {
      setShowDeleteModal(true);
    }
  };

  const handleSaveGroup = async (isNew: boolean) => {
    if (!cluster || !editingGroup.name || !id) return;

    setSavingGroup(true);
    try {
      let updatedGroups: InstanceGroup[];
      if (isNew) {
        updatedGroups = [...(cluster.instance_groups || []), editingGroup];
      } else {
        updatedGroups = (cluster.instance_groups || []).map(g =>
          g.name === selectedInstanceGroups[0]?.name ? editingGroup : g
        );
      }

      // Call API to update cluster instance groups
      const response = await updateClusterInstanceGroups(id, updatedGroups);

      // API returns { response_id, response: { statusCode, body } }
      const statusCode = response?.response?.statusCode ?? response?.statusCode;
      const body = response?.response?.body ?? response?.body;

      if (statusCode === 200) {
        // Reload cluster data
        await loadCluster(id);
        setShowAddModal(false);
        setShowEditModal(false);
        setSelectedInstanceGroups([]);

        const successId = `ig-${Date.now()}`;
        setNotificationItems((items: any) => [
          ...items,
          {
            type: 'success',
            content: isNew ? t('instance_group_added') : t('instance_group_updated'),
            dismissible: true,
            id: successId,
            onDismiss: () => setNotificationItems((items: any) => items.filter((item: any) => item.id !== successId)),
          },
        ]);
      } else {
        throw new Error(body?.message || body || 'Failed to update instance groups');
      }
    } catch (error: any) {
      const errorId = `ig-error-${Date.now()}`;
      setNotificationItems((items: any) => [
        ...items,
        {
          type: 'error',
          content: `${t('error')}: ${error.message || error}`,
          dismissible: true,
          id: errorId,
          onDismiss: () => setNotificationItems((items: any) => items.filter((item: any) => item.id !== errorId)),
        },
      ]);
    } finally {
      setSavingGroup(false);
    }
  };

  const handleConfirmDelete = async () => {
    if (!cluster || !id) return;

    setSavingGroup(true);
    try {
      const namesToDelete = selectedInstanceGroups.map(g => g.name);
      const updatedGroups = (cluster.instance_groups || []).filter(g => !namesToDelete.includes(g.name));

      // Call API to update cluster instance groups
      const response = await updateClusterInstanceGroups(id, updatedGroups);

      // API returns { response_id, response: { statusCode, body } }
      const statusCode = response?.response?.statusCode ?? response?.statusCode;
      const body = response?.response?.body ?? response?.body;

      if (statusCode === 200) {
        // Reload cluster data
        await loadCluster(id);
        setShowDeleteModal(false);
        setSelectedInstanceGroups([]);

        const successId = `ig-delete-${Date.now()}`;
        setNotificationItems((items: any) => [
          ...items,
          {
            type: 'success',
            content: `${t('instance_group_deleted')}: ${selectedInstanceGroups.length}`,
            dismissible: true,
            id: successId,
            onDismiss: () => setNotificationItems((items: any) => items.filter((item: any) => item.id !== successId)),
          },
        ]);
      } else {
        throw new Error(body?.message || body || 'Failed to delete instance groups');
      }
    } catch (error: any) {
      const errorId = `ig-delete-error-${Date.now()}`;
      setNotificationItems((items: any) => [
        ...items,
        {
          type: 'error',
          content: `${t('error')}: ${error.message || error}`,
          dismissible: true,
          id: errorId,
          onDismiss: () => setNotificationItems((items: any) => items.filter((item: any) => item.id !== errorId)),
        },
      ]);
    } finally {
      setSavingGroup(false);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding="xxl">
        <Spinner size="large" />
        <Box variant="p" padding={{ top: 's' }}>{t('loading_cluster')}</Box>
      </Box>
    );
  }

  if (!cluster || !cluster.cluster_name) {
    return (
      <Box textAlign="center" padding="xxl">
        <Box variant="h2">{t('cluster_not_found')}</Box>
        <Box variant="p" padding={{ top: 's' }}>
          {t('cluster_not_found_desc')}
        </Box>
        <Button onClick={() => navigate('/clusters')} variant="primary">
          {t('back_to_clusters')}
        </Button>
      </Box>
    );
  }

  const clusterConfig = cluster.cluster_config || {};
  const eksConfig = clusterConfig.eks_config || {};
  const hyperpodConfig = clusterConfig.hyperpod_config || {};

  return (
    <SpaceBetween size="l">
      {/* Header */}
      <Header
        variant="h1"
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button iconName="refresh" onClick={handleRefresh}>
              {t('refresh')}
            </Button>
            <Button onClick={() => navigate('/clusters')}>
              {t('back_to_clusters')}
            </Button>
          </SpaceBetween>
        }
      >
        {cluster.cluster_name}
      </Header>

      {/* Error Message */}
      {cluster.error_message && !errorDismissed && (
        <Flashbar
          items={[
            {
              type: 'error',
              header: t('cluster_error'),
              content: cluster.error_message,
              dismissible: true,
              dismissLabel: t('dismiss'),
              onDismiss: () => setErrorDismissed(true),
            },
          ]}
        />
      )}

      {/* Tabs */}
      <Tabs
        activeTabId={activeTabId}
        onChange={({ detail }) => {
          setActiveTabId(detail.activeTabId);
          // Load nodes when instances or instance-groups tab is selected for the first time
          if ((detail.activeTabId === 'instances' || detail.activeTabId === 'instance-groups') && clusterNodes.length === 0 && id) {
            loadNodes(id);
          }
        }}
        tabs={[
          {
            id: 'overview',
            label: t('overview'),
            content: (
              <SpaceBetween size="l">
                {/* Basic Info */}
                <Container header={<Header variant="h2">{t('cluster_info')}</Header>}>
                  <ColumnLayout columns={2} variant="text-grid">
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">{t('cluster_name')}</Box>
                        <div>{cluster.cluster_name}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">{t('cluster_id')}</Box>
                        <CopyToClipboard
                          textToCopy={cluster.cluster_id}
                          copyButtonAriaLabel={t('copy')}
                          copySuccessText={t('copied')}
                          copyErrorText={t('error')}
                          variant="inline"
                        />
                      </div>
                      <div>
                        <Box variant="awsui-key-label">{t('status')}</Box>
                        <StatusIndicator type={statusTypeMap[cluster.cluster_status] || 'pending'}>
                          {statusLabelMap[cluster.cluster_status] || cluster.cluster_status}
                        </StatusIndicator>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">{t('created')}</Box>
                        <div>{cluster.cluster_create_time || '-'}</div>
                      </div>
                    </SpaceBetween>
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">{t('eks_cluster_name')}</Box>
                        <div>{cluster.eks_cluster_name || '-'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">EKS Cluster ARN</Box>
                        <div style={{ wordBreak: 'break-all' }}>{cluster.eks_cluster_arn || '-'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">HyperPod Cluster ARN</Box>
                        <div style={{ wordBreak: 'break-all' }}>{cluster.hyperpod_cluster_arn || '-'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">{t('last_updated')}</Box>
                        <div>{cluster.cluster_update_time || '-'}</div>
                      </div>
                    </SpaceBetween>
                  </ColumnLayout>
                </Container>

                {/* Configuration */}
                <Container header={<Header variant="h2">{t('configuration')}</Header>}>
                  <ColumnLayout columns={2} variant="text-grid">
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">{t('kubernetes_version')}</Box>
                        <div>{eksConfig.kubernetes_version || '-'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">{t('node_recovery')}</Box>
                        <div>{hyperpodConfig.node_recovery || t('automatic')}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">{t('enable_tiered_storage')}</Box>
                        <div>
                          {hyperpodConfig.enable_tiered_storage ? (
                            <StatusIndicator type="success">
                              {t('enable')} ({hyperpodConfig.tiered_storage_memory_percentage || 20}%)
                            </StatusIndicator>
                          ) : (
                            <StatusIndicator type="stopped">{t('false')}</StatusIndicator>
                          )}
                        </div>
                      </div>
                    </SpaceBetween>
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">{t('enable_karpenter')}</Box>
                        <div>{hyperpodConfig.enable_autoscaling ? t('enable') : t('false')}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">{t('lifecycle_script_s3')}</Box>
                        <div style={{ wordBreak: 'break-all' }}>
                          {clusterConfig.lifecycle_script_s3_uri || getDefaultLifecycleScriptUri(cluster)}
                          {!clusterConfig.lifecycle_script_s3_uri && cluster.hyperpod_cluster_arn && (
                            <Box variant="span" color="text-status-inactive" fontSize="body-s"> (default)</Box>
                          )}
                        </div>
                      </div>
                    </SpaceBetween>
                  </ColumnLayout>
                </Container>

                {/* VPC Info */}
                <Container header={<Header variant="h2">{t('network_config')}</Header>}>
                  <ColumnLayout columns={2} variant="text-grid">
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">{t('vpc_id')}</Box>
                        <div>{cluster.vpc_id || '-'}</div>
                      </div>
                    </SpaceBetween>
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">{t('subnets')}</Box>
                        <div>{cluster.subnet_ids?.join(', ') || '-'}</div>
                      </div>
                    </SpaceBetween>
                  </ColumnLayout>
                </Container>
              </SpaceBetween>
            ),
          },
          {
            id: 'instance-groups',
            label: t('instance_groups'),
            content: (() => {
              // Check if cluster is in a transitional state
              const isTransitionalState = ['PENDING', 'CREATING', 'UPDATING', 'DELETING'].includes(cluster.cluster_status);
              const actionsDisabled = isTransitionalState;

              return (
              <Container
                header={
                  <Header
                    variant="h2"
                    description={isTransitionalState
                      ? t('cannot_modify_transitional')
                      : t('instance_groups_desc')
                    }
                    actions={
                      <SpaceBetween direction="horizontal" size="xs">
                        <Button
                          disabled={actionsDisabled || selectedInstanceGroups.length !== 1}
                          onClick={handleEditGroup}
                        >
                          {t('edit')}
                        </Button>
                        <Button
                          disabled={actionsDisabled || selectedInstanceGroups.length === 0}
                          onClick={handleDeleteGroup}
                        >
                          {t('delete')}
                        </Button>
                        <Button variant="primary" onClick={handleAddGroup} disabled={actionsDisabled}>
                          {t('add_group')}
                        </Button>
                      </SpaceBetween>
                    }
                  >
                    {t('instance_groups')}
                  </Header>
                }
              >
                <Table
                  items={cluster.instance_groups || []}
                  selectionType="multi"
                  selectedItems={selectedInstanceGroups}
                  onSelectionChange={({ detail }) => setSelectedInstanceGroups(detail.selectedItems)}
                  trackBy="name"
                  columnDefinitions={[
                    {
                      id: 'name',
                      header: t('name'),
                      cell: (item: InstanceGroup) => item.name,
                    },
                    {
                      id: 'instance_type',
                      header: t('instance_type'),
                      cell: (item: InstanceGroup) => item.instance_type,
                    },
                    {
                      id: 'instance_count',
                      header: t('desired'),
                      cell: (item: InstanceGroup) => item.instance_count,
                    },
                    {
                      id: 'current_count',
                      header: t('current'),
                      cell: (item: InstanceGroup) => {
                        if (nodesLoading) {
                          return <Spinner size="normal" />;
                        }
                        const currentCount = clusterNodes.filter(
                          node => node.instance_group_name === item.name
                        ).length;
                        return currentCount;
                      },
                    },
                    {
                      id: 'available_count',
                      header: t('available'),
                      cell: (item: InstanceGroup) => {
                        if (nodesLoading) {
                          return <Spinner size="normal" />;
                        }
                        const groupNodes = clusterNodes.filter(
                          node => node.instance_group_name === item.name
                        );
                        const availableCount = groupNodes.filter(node => !node.is_occupied).length;
                        const totalCount = groupNodes.length;
                        return (
                          <StatusIndicator type={availableCount > 0 ? 'success' : 'warning'}>
                            {availableCount} / {totalCount}
                          </StatusIndicator>
                        );
                      },
                    },
                    {
                      id: 'min_instance_count',
                      header: t('min_instance_count'),
                      cell: (item: InstanceGroup) => item.min_instance_count ?? '-',
                    },
                    {
                      id: 'storage_volume_size',
                      header: t('storage_volume_size'),
                      cell: (item: InstanceGroup) => item.storage_volume_size ?? 500,
                    },
                    {
                      id: 'use_spot',
                      header: t('capacity'),
                      cell: (item: InstanceGroup) => item.use_spot ? t('spot') : t('on_demand'),
                    },
                    {
                      id: 'training_plan_arn',
                      header: t('training_plan_arn'),
                      cell: (item: InstanceGroup) => item.training_plan_arn || '-',
                    },
                    {
                      id: 'health_checks',
                      header: t('deep_health_checks'),
                      cell: (item: InstanceGroup) => {
                        const checks = [];
                        if (item.enable_instance_stress_check) checks.push(t('stress'));
                        if (item.enable_instance_connectivity_check) checks.push(t('connectivity'));
                        return checks.length > 0 ? checks.join(', ') : '-';
                      },
                    },
                  ]}
                  empty={
                    <Box textAlign="center" color="inherit">
                      <b>{t('no_instance_groups')}</b>
                      <Box padding={{ bottom: 's' }} variant="p" color="inherit">
                        {t('no_instance_groups_desc')}
                      </Box>
                    </Box>
                  }
                />
              </Container>
              );
            })(),
          },
          {
            id: 'instances',
            label: t('instances'),
            content: (
              <Container
                header={
                  <Header
                    variant="h2"
                    actions={
                      <SpaceBetween direction="horizontal" size="xs">
                        <Box color="text-body-secondary" fontSize="body-s">
                          {nodesLastUpdated && `${t('last_updated')}: ${nodesLastUpdated.toLocaleString()}`}
                        </Box>
                        <Button
                          iconName="refresh"
                          onClick={handleRefreshNodes}
                          loading={nodesLoading}
                        />
                      </SpaceBetween>
                    }
                  >
                    {t('instances')} ({clusterNodes.length})
                  </Header>
                }
              >
                <Table
                  items={clusterNodes}
                  loading={nodesLoading}
                  loadingText="Loading instances..."
                  columnDefinitions={[
                    {
                      id: 'instance_id',
                      header: 'Instance',
                      cell: (item: ClusterNode) => item.instance_id,
                    },
                    {
                      id: 'instance_status',
                      header: 'Status',
                      cell: (item: ClusterNode) => {
                        const statusMap: Record<string, 'success' | 'pending' | 'error' | 'in-progress'> = {
                          'Running': 'success',
                          'Pending': 'pending',
                          'ShuttingDown': 'in-progress',
                          'Terminated': 'error',
                          'Stopping': 'in-progress',
                          'Stopped': 'error',
                        };
                        return (
                          <StatusIndicator type={statusMap[item.instance_status] || 'pending'}>
                            {item.instance_status}
                          </StatusIndicator>
                        );
                      },
                    },
                    {
                      id: 'instance_group_name',
                      header: 'Instance group',
                      cell: (item: ClusterNode) => item.instance_group_name,
                    },
                    {
                      id: 'instance_type',
                      header: 'Instance type',
                      cell: (item: ClusterNode) => item.instance_type || '-',
                    },
                    {
                      id: 'launch_time',
                      header: 'Created',
                      cell: (item: ClusterNode) => item.launch_time ? new Date(item.launch_time).toLocaleString() : '-',
                    },
                    {
                      id: 'is_occupied',
                      header: 'Status',
                      cell: (item: ClusterNode) => (
                        <StatusIndicator type={item.is_occupied ? 'warning' : 'success'}>
                          {item.is_occupied ? 'Occupied' : 'Available'}
                        </StatusIndicator>
                      ),
                    },
                    {
                      id: 'occupied_by',
                      header: 'Occupied By',
                      cell: (item: ClusterNode) => item.occupied_by || '-',
                    },
                  ]}
                  empty={
                    <Box textAlign="center" color="inherit">
                      <b>No instances</b>
                      <Box padding={{ bottom: 's' }} variant="p" color="inherit">
                        {cluster?.cluster_status === 'ACTIVE'
                          ? 'Click the refresh button to load instances.'
                          : 'Instances will be available when the cluster is active.'}
                      </Box>
                    </Box>
                  }
                />
              </Container>
            ),
          },
        ]}
      />

      {/* Add Instance Group Modal */}
      <Modal
        visible={showAddModal}
        onDismiss={() => setShowAddModal(false)}
        header={t('add_instance_group_title')}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowAddModal(false)}>
                {t('cancel')}
              </Button>
              <Button variant="primary" onClick={() => handleSaveGroup(true)} loading={savingGroup}>
                {t('add_group')}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <InstanceGroupForm group={editingGroup} setGroup={setEditingGroup} t={t} subnets={clusterSubnets} subnetsLoading={subnetsLoading} instanceTypeAzs={instanceTypeAzs} onInstanceTypeChange={loadInstanceTypeAzs} />
      </Modal>

      {/* Edit Instance Group Modal */}
      <Modal
        visible={showEditModal}
        onDismiss={() => setShowEditModal(false)}
        header={t('edit_instance_group_title')}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowEditModal(false)}>
                {t('cancel')}
              </Button>
              <Button variant="primary" onClick={() => handleSaveGroup(false)} loading={savingGroup}>
                {t('save_changes')}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <InstanceGroupForm group={editingGroup} setGroup={setEditingGroup} t={t} subnets={clusterSubnets} subnetsLoading={subnetsLoading} instanceTypeAzs={instanceTypeAzs} onInstanceTypeChange={loadInstanceTypeAzs} />
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        visible={showDeleteModal}
        onDismiss={() => setShowDeleteModal(false)}
        header={t('delete_instance_group_title')}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowDeleteModal(false)}>
                {t('cancel')}
              </Button>
              <Button variant="primary" onClick={handleConfirmDelete} loading={savingGroup}>
                {t('delete')}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <Box variant="p">
          {t('confirm_delete_instance_groups')}
        </Box>
        <Box variant="p" fontWeight="bold">
          {selectedInstanceGroups.map(g => g.name).join(', ')}
        </Box>
      </Modal>
    </SpaceBetween>
  );
}

// Instance Group Form Component
function InstanceGroupForm({
  group,
  setGroup,
  t,
  subnets,
  subnetsLoading,
  instanceTypeAzs,
  onInstanceTypeChange,
}: {
  group: InstanceGroup;
  setGroup: React.Dispatch<React.SetStateAction<InstanceGroup>>;
  t: (key: string) => string;
  subnets: SubnetInfo[];
  subnetsLoading: boolean;
  instanceTypeAzs: string[];
  onInstanceTypeChange: (instanceType: string) => void;
}) {
  // Build subnet options for dropdown, marking which ones support the instance type
  // Filter out public subnets - only show private subnets for instance groups
  // Check both is_public flag and subnet name for "public" keyword
  const privateSubnets = subnets.filter(subnet =>
    !subnet.is_public && !(subnet.name?.toLowerCase().includes('public'))
  );
  const subnetOptions = [
    { label: t('use_cluster_default'), value: '', description: '' },
    ...privateSubnets.map(subnet => {
      const isSupported = instanceTypeAzs.length === 0 || instanceTypeAzs.includes(subnet.availability_zone);
      const supportLabel = isSupported ? '' : ' [NOT SUPPORTED]';
      return {
        label: `${subnet.name || subnet.subnet_id} (${subnet.availability_zone})${supportLabel}`,
        value: subnet.subnet_id,
        description: `${subnet.subnet_id} - ${subnet.cidr_block || ''}`,
        disabled: !isSupported,
      };
    }),
  ];

  return (
    <SpaceBetween size="l">
      <FormField label={t('group_name')}>
        <Input
          value={group.name}
          onChange={({ detail }) => setGroup({ ...group, name: detail.value })}
          placeholder="worker-group-1"
        />
      </FormField>
      <FormField label={t('instance_type')}>
        <Select
          selectedOption={instanceTypeOptions.find(opt => opt.value === group.instance_type) || null}
          onChange={({ detail }) => {
            const newInstanceType = detail.selectedOption?.value || 'ml.g5.xlarge';
            setGroup({ ...group, instance_type: newInstanceType, override_subnet_id: '' });
            onInstanceTypeChange(newInstanceType);
          }}
          options={instanceTypeOptions}
        />
      </FormField>
      <SpaceBetween direction="horizontal" size="l">
        <FormField label={t('instance_count')}>
          <Input
            type="number"
            value={String(group.instance_count)}
            onChange={({ detail }) => setGroup({ ...group, instance_count: parseInt(detail.value) || 0 })}
          />
        </FormField>
        <FormField label={t('min_instance_count')}>
          <Input
            type="number"
            value={String(group.min_instance_count ?? 0)}
            onChange={({ detail }) => setGroup({ ...group, min_instance_count: parseInt(detail.value) || 0 })}
          />
        </FormField>
      </SpaceBetween>
      <FormField label={t('storage_volume_size')}>
        <Input
          type="number"
          value={String(group.storage_volume_size || 500)}
          onChange={({ detail }) => setGroup({ ...group, storage_volume_size: parseInt(detail.value) || 500 })}
        />
      </FormField>
      <FormField label={t('training_plan_arn')} description={t('optional')}>
        <Input
          value={group.training_plan_arn || ''}
          onChange={({ detail }) => setGroup({ ...group, training_plan_arn: detail.value })}
          placeholder="arn:aws:sagemaker:region:account:training-plan/plan-id"
        />
      </FormField>
      <Checkbox
        checked={group.use_spot || false}
        onChange={({ detail }) => setGroup({ ...group, use_spot: detail.checked })}
      >
        {t('use_spot_instances')}
      </Checkbox>
      {group.use_spot && (
        <SpotPriceInfo
          instanceType={group.instance_type}
          useSpot={group.use_spot}
        />
      )}
      {/* Override Subnet/AZ selection - especially useful for spot instances */}
      {group.use_spot && (
        <>
          {instanceTypeAzs.length > 0 && (
            <Box variant="small" color="text-body-secondary">
              <StatusIndicator type="info">
                {t('instance_type_az_info')}{instanceTypeAzs.join(', ')}
              </StatusIndicator>
            </Box>
          )}
          <FormField
            label={t('override_subnet')}
            description={t('override_subnet_desc')}
          >
            <Select
              selectedOption={subnetOptions.find(opt => opt.value === (group.override_subnet_id || '')) || subnetOptions[0]}
              onChange={({ detail }) => setGroup({ ...group, override_subnet_id: detail.selectedOption?.value || '' })}
              options={subnetOptions}
              statusType={subnetsLoading ? 'loading' : 'finished'}
              loadingText={t('loading')}
            />
          </FormField>
        </>
      )}
      <Checkbox
        checked={group.enable_instance_stress_check || false}
        onChange={({ detail }) => setGroup({ ...group, enable_instance_stress_check: detail.checked })}
      >
        {t('enable_stress_check')}
      </Checkbox>
      <Checkbox
        checked={group.enable_instance_connectivity_check || false}
        onChange={({ detail }) => setGroup({ ...group, enable_instance_connectivity_check: detail.checked })}
      >
        {t('enable_connectivity_check')}
      </Checkbox>
    </SpaceBetween>
  );
}

const clusterDetailBreadcrumbs = [
  { text: 'HyperPod Clusters', href: '/clusters' },
  { text: 'Cluster Details', href: '#' },
];

function ClusterDetailApp() {
  const appLayout = useRef<any>();
  const { notificationitems } = useSimpleNotifications();

  return (
    <div>
      <TopNav />
      <CustomAppLayout
        ref={appLayout}
        navigation={<Navigation activeHref="/clusters" />}
        notifications={<Flashbar items={notificationitems} stackItems />}
        breadcrumbs={<Breadcrumbs items={clusterDetailBreadcrumbs} />}
        content={<ClusterDetailContent />}
        contentType="default"
      />
    </div>
  );
}

export default ClusterDetailApp;
