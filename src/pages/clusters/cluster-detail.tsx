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
import { getCluster, updateClusterInstanceGroups, listClusterNodes } from './hooks';
import { useSimpleNotifications } from '../commons/use-notifications';

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
}

interface ClusterNode {
  instance_id: string;
  instance_status: string;
  instance_group_name: string;
  instance_type?: string;
  launch_time?: string;
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
    };
    lifecycle_script_s3_uri?: string;
  };
}

const instanceTypeOptions = [
  { label: 'ml.c5.large (CPU)', value: 'ml.c5.large' },
  { label: 'ml.c5.xlarge (CPU)', value: 'ml.c5.xlarge' },
  { label: 'ml.g5.xlarge (1x A10G)', value: 'ml.g5.xlarge' },
  { label: 'ml.g5.2xlarge (1x A10G)', value: 'ml.g5.2xlarge' },
  { label: 'ml.g5.4xlarge (1x A10G)', value: 'ml.g5.4xlarge' },
  { label: 'ml.g5.8xlarge (1x A10G)', value: 'ml.g5.8xlarge' },
  { label: 'ml.g5.12xlarge (4x A10G)', value: 'ml.g5.12xlarge' },
  { label: 'ml.g5.24xlarge (4x A10G)', value: 'ml.g5.24xlarge' },
  { label: 'ml.g5.48xlarge (8x A10G)', value: 'ml.g5.48xlarge' },
  { label: 'ml.p4d.24xlarge (8x A100 40GB)', value: 'ml.p4d.24xlarge' },
  { label: 'ml.p4de.24xlarge (8x A100 80GB)', value: 'ml.p4de.24xlarge' },
  { label: 'ml.p5.48xlarge (8x H100)', value: 'ml.p5.48xlarge' },
  { label: 'ml.p5e.48xlarge (8x H200)', value: 'ml.p5e.48xlarge' },
  { label: 'ml.p5en.48xlarge (8x H200)', value: 'ml.p5en.48xlarge' },
];

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
    return `s3://llm-modelhub-hyperpod-${arnInfo.accountId}-${arnInfo.region}/hyperpod-scripts/`;
  }
  return '-';
}

function ClusterDetailContent() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
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

  useEffect(() => {
    if (id) {
      loadCluster(id);
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

  const handleAddGroup = () => {
    setEditingGroup({ ...emptyInstanceGroup, name: `instance-group-${(cluster?.instance_groups?.length || 0) + 1}` });
    setShowAddModal(true);
  };

  const handleEditGroup = () => {
    if (selectedInstanceGroups.length === 1) {
      setEditingGroup({ ...selectedInstanceGroups[0] });
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
            content: isNew ? 'Instance group added successfully' : 'Instance group updated successfully',
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
          content: `Failed to ${isNew ? 'add' : 'update'} instance group: ${error.message || error}`,
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
            content: `Deleted ${selectedInstanceGroups.length} instance group(s)`,
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
          content: `Failed to delete instance group(s): ${error.message || error}`,
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
        <Box variant="p" padding={{ top: 's' }}>Loading cluster details...</Box>
      </Box>
    );
  }

  if (!cluster || !cluster.cluster_name) {
    return (
      <Box textAlign="center" padding="xxl">
        <Box variant="h2">Cluster not found</Box>
        <Box variant="p" padding={{ top: 's' }}>
          The cluster you're looking for doesn't exist or has been deleted.
        </Box>
        <Button onClick={() => navigate('/clusters')} variant="primary">
          Back to Clusters
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
              Refresh
            </Button>
            <Button onClick={() => navigate('/clusters')}>
              Back to Clusters
            </Button>
          </SpaceBetween>
        }
      >
        {cluster.cluster_name}
      </Header>

      {/* Error Message */}
      {cluster.error_message && (
        <Flashbar
          items={[
            {
              type: 'error',
              header: 'Cluster Error',
              content: cluster.error_message,
              dismissible: false,
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
            label: 'Overview',
            content: (
              <SpaceBetween size="l">
                {/* Basic Info */}
                <Container header={<Header variant="h2">Cluster Information</Header>}>
                  <ColumnLayout columns={2} variant="text-grid">
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">Cluster Name</Box>
                        <div>{cluster.cluster_name}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Cluster ID</Box>
                        <CopyToClipboard
                          textToCopy={cluster.cluster_id}
                          copyButtonAriaLabel="Copy cluster ID"
                          copySuccessText="Cluster ID copied"
                          copyErrorText="Failed to copy"
                          variant="inline"
                        />
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Status</Box>
                        <StatusIndicator type={statusTypeMap[cluster.cluster_status] || 'pending'}>
                          {statusLabelMap[cluster.cluster_status] || cluster.cluster_status}
                        </StatusIndicator>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Created</Box>
                        <div>{cluster.cluster_create_time || '-'}</div>
                      </div>
                    </SpaceBetween>
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">EKS Cluster Name</Box>
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
                        <Box variant="awsui-key-label">Last Updated</Box>
                        <div>{cluster.cluster_update_time || '-'}</div>
                      </div>
                    </SpaceBetween>
                  </ColumnLayout>
                </Container>

                {/* Configuration */}
                <Container header={<Header variant="h2">Configuration</Header>}>
                  <ColumnLayout columns={2} variant="text-grid">
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">Kubernetes Version</Box>
                        <div>{eksConfig.kubernetes_version || '-'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Node Recovery</Box>
                        <div>{hyperpodConfig.node_recovery || 'Automatic'}</div>
                      </div>
                    </SpaceBetween>
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">Karpenter Autoscaling</Box>
                        <div>{hyperpodConfig.enable_autoscaling ? 'Enabled' : 'Disabled'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Lifecycle Script S3 URI</Box>
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
                <Container header={<Header variant="h2">Network Configuration</Header>}>
                  <ColumnLayout columns={2} variant="text-grid">
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">VPC ID</Box>
                        <div>{cluster.vpc_id || '-'}</div>
                      </div>
                    </SpaceBetween>
                    <SpaceBetween size="l">
                      <div>
                        <Box variant="awsui-key-label">Subnets</Box>
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
            label: 'Instance Groups',
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
                      ? `Instance groups cannot be modified while cluster is ${statusLabelMap[cluster.cluster_status] || cluster.cluster_status}.`
                      : "Add and configure the groups of compute instances."
                    }
                    actions={
                      <SpaceBetween direction="horizontal" size="xs">
                        <Button
                          disabled={actionsDisabled || selectedInstanceGroups.length !== 1}
                          onClick={handleEditGroup}
                        >
                          Edit
                        </Button>
                        <Button
                          disabled={actionsDisabled || selectedInstanceGroups.length === 0}
                          onClick={handleDeleteGroup}
                        >
                          Delete
                        </Button>
                        <Button variant="primary" onClick={handleAddGroup} disabled={actionsDisabled}>
                          Add group
                        </Button>
                      </SpaceBetween>
                    }
                  >
                    Instance Groups
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
                      header: 'Name',
                      cell: (item: InstanceGroup) => item.name,
                    },
                    {
                      id: 'instance_type',
                      header: 'Instance Type',
                      cell: (item: InstanceGroup) => item.instance_type,
                    },
                    {
                      id: 'instance_count',
                      header: 'Desired',
                      cell: (item: InstanceGroup) => item.instance_count,
                    },
                    {
                      id: 'current_count',
                      header: 'Current',
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
                      id: 'min_instance_count',
                      header: 'Min Count',
                      cell: (item: InstanceGroup) => item.min_instance_count ?? '-',
                    },
                    {
                      id: 'storage_volume_size',
                      header: 'Storage (GB)',
                      cell: (item: InstanceGroup) => item.storage_volume_size ?? 500,
                    },
                    {
                      id: 'use_spot',
                      header: 'Capacity',
                      cell: (item: InstanceGroup) => item.use_spot ? 'Spot' : 'On-demand',
                    },
                    {
                      id: 'training_plan_arn',
                      header: 'Training Plan',
                      cell: (item: InstanceGroup) => item.training_plan_arn || '-',
                    },
                    {
                      id: 'health_checks',
                      header: 'Deep Health Checks',
                      cell: (item: InstanceGroup) => {
                        const checks = [];
                        if (item.enable_instance_stress_check) checks.push('Stress');
                        if (item.enable_instance_connectivity_check) checks.push('Connectivity');
                        return checks.length > 0 ? checks.join(', ') : '-';
                      },
                    },
                  ]}
                  empty={
                    <Box textAlign="center" color="inherit">
                      <b>No instance groups</b>
                      <Box padding={{ bottom: 's' }} variant="p" color="inherit">
                        This cluster has no instance groups configured.
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
            label: 'Instances',
            content: (
              <Container
                header={
                  <Header
                    variant="h2"
                    description="Gain detailed information about the individual compute instances in the HyperPod cluster."
                    actions={
                      <SpaceBetween direction="horizontal" size="xs">
                        <Box color="text-body-secondary" fontSize="body-s">
                          {nodesLastUpdated && `Last updated: ${nodesLastUpdated.toLocaleString()}`}
                        </Box>
                        <Button
                          iconName="refresh"
                          onClick={handleRefreshNodes}
                          loading={nodesLoading}
                        />
                      </SpaceBetween>
                    }
                  >
                    Instances ({clusterNodes.length})
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
        header="Add instance group"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowAddModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => handleSaveGroup(true)} loading={savingGroup}>
                Add group
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <InstanceGroupForm group={editingGroup} setGroup={setEditingGroup} />
      </Modal>

      {/* Edit Instance Group Modal */}
      <Modal
        visible={showEditModal}
        onDismiss={() => setShowEditModal(false)}
        header="Edit instance group"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowEditModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => handleSaveGroup(false)} loading={savingGroup}>
                Save changes
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <InstanceGroupForm group={editingGroup} setGroup={setEditingGroup} />
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        visible={showDeleteModal}
        onDismiss={() => setShowDeleteModal(false)}
        header="Delete instance group(s)"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowDeleteModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleConfirmDelete} loading={savingGroup}>
                Delete
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <Box variant="p">
          Are you sure you want to delete the following instance group(s)?
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
}: {
  group: InstanceGroup;
  setGroup: React.Dispatch<React.SetStateAction<InstanceGroup>>;
}) {
  return (
    <SpaceBetween size="l">
      <FormField label="Group name">
        <Input
          value={group.name}
          onChange={({ detail }) => setGroup({ ...group, name: detail.value })}
          placeholder="instance-group-1"
        />
      </FormField>
      <FormField label="Instance type">
        <Select
          selectedOption={instanceTypeOptions.find(opt => opt.value === group.instance_type) || null}
          onChange={({ detail }) => setGroup({ ...group, instance_type: detail.selectedOption?.value || 'ml.g5.xlarge' })}
          options={instanceTypeOptions}
        />
      </FormField>
      <SpaceBetween direction="horizontal" size="l">
        <FormField label="Instance count">
          <Input
            type="number"
            value={String(group.instance_count)}
            onChange={({ detail }) => setGroup({ ...group, instance_count: parseInt(detail.value) || 0 })}
          />
        </FormField>
        <FormField label="Min instance count">
          <Input
            type="number"
            value={String(group.min_instance_count ?? 0)}
            onChange={({ detail }) => setGroup({ ...group, min_instance_count: parseInt(detail.value) || 0 })}
          />
        </FormField>
      </SpaceBetween>
      <FormField label="Storage volume (GB)">
        <Input
          type="number"
          value={String(group.storage_volume_size || 500)}
          onChange={({ detail }) => setGroup({ ...group, storage_volume_size: parseInt(detail.value) || 500 })}
        />
      </FormField>
      <FormField label="Training Plan ARN" description="Optional">
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
        Use Spot Instances
      </Checkbox>
      <Checkbox
        checked={group.enable_instance_stress_check || false}
        onChange={({ detail }) => setGroup({ ...group, enable_instance_stress_check: detail.checked })}
      >
        Enable InstanceStress Deep Health Check
      </Checkbox>
      <Checkbox
        checked={group.enable_instance_connectivity_check || false}
        onChange={({ detail }) => setGroup({ ...group, enable_instance_connectivity_check: detail.checked })}
      >
        Enable InstanceConnectivity Deep Health Check
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
