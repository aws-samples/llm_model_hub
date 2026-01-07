// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useState, useRef } from 'react';
import {
  Box,
  Button,
  Container,
  Form,
  FormField,
  Header,
  Input,
  Select,
  SpaceBetween,
  Tiles,
  ExpandableSection,
  Checkbox,
  Flashbar,
  AttributeEditor,
} from '@cloudscape-design/components';
import { useNavigate } from 'react-router-dom';
import { CustomAppLayout, Navigation } from '../commons/common-components';
import { Breadcrumbs } from '../commons/breadcrumbs';
import { TopNav } from '../commons/top-nav';
import { createCluster } from './hooks';
import { useSimpleNotifications } from '../commons/use-notifications';
import SpotPriceInfo from '../commons/spot-price-info';
import { useTranslation } from 'react-i18next';

const instanceTypeOptions = [
  { label: 'ml.c5.large (CPU)', value: 'ml.c5.large' },
  { label: 'ml.c5.xlarge (CPU)', value: 'ml.c5.xlarge' },
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

const kubernetesVersionOptions = [
  { label: '1.33 (Recommended)', value: '1.33' },
  { label: '1.32', value: '1.32' },
  { label: '1.31', value: '1.31' },
  { label: '1.30', value: '1.30' },
  { label: '1.29', value: '1.29' },
];

interface InstanceGroup {
  name: string;
  instance_type: string;
  instance_count: number;
  min_instance_count?: number;
  use_spot: boolean;
  training_plan_arn?: string;
  storage_volume_size?: number;
  enable_instance_stress_check?: boolean;
  enable_instance_connectivity_check?: boolean;
}

const clusterBreadcrumbs = [
  { text: 'Model Hub', href: '/' },
  { text: 'HyperPod Clusters', href: '/clusters' },
  { text: 'Create Cluster', href: '/clusters/create' },
];

function CreateClusterContent() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { setNotificationItems } = useSimpleNotifications();
  const [submitting, setSubmitting] = useState(false);

  // Form state
  const [clusterName, setClusterName] = useState('');
  const [eksClusterName, setEksClusterName] = useState('');
  const [kubernetesVersion, setKubernetesVersion] = useState({ label: '1.33 (Recommended)', value: '1.33' });
  const [instanceGroups, setInstanceGroups] = useState<InstanceGroup[]>([
    {
      name: 'worker-group-1',
      instance_type: 'ml.g5.4xlarge',
      instance_count: 1,
      min_instance_count: 0,
      use_spot: false,
      training_plan_arn: '',
      storage_volume_size: 500,
      enable_instance_stress_check: false,
      enable_instance_connectivity_check: false,
    },
  ]);

  // Advanced settings
  const [nodeRecovery, setNodeRecovery] = useState('Automatic');
  const [enableAutoscaling, setEnableAutoscaling] = useState(false);
  const [lifecycleScriptS3Uri, setLifecycleScriptS3Uri] = useState('');
  const [s3MountBucket, setS3MountBucket] = useState('');

  // VPC settings
  const [useExistingVpc, setUseExistingVpc] = useState(false);
  const [vpcId, setVpcId] = useState('');
  const [subnetIds, setSubnetIds] = useState('');
  const [securityGroupIds, setSecurityGroupIds] = useState('');

  const handleSubmit = async () => {
    if (!clusterName) {
      setNotificationItems((items: any) => [
        ...items,
        {
          type: 'error',
          content: t('cluster_name_required'),
          dismissible: true,
          id: 'validation-error',
        },
      ]);
      return;
    }

    if (instanceGroups.length === 0) {
      setNotificationItems((items: any) => [
        ...items,
        {
          type: 'error',
          content: t('instance_group_required'),
          dismissible: true,
          id: 'validation-error-ig',
        },
      ]);
      return;
    }

    setSubmitting(true);

    const requestData: any = {
      cluster_name: clusterName,
      eks_cluster_name: eksClusterName || undefined,
      instance_groups: instanceGroups,
      eks_config: {
        kubernetes_version: kubernetesVersion.value,
      },
      hyperpod_config: {
        node_recovery: nodeRecovery,
        enable_autoscaling: enableAutoscaling,
      },
      lifecycle_script_s3_uri: lifecycleScriptS3Uri || undefined,
      s3_mount_bucket: s3MountBucket || undefined,
    };

    if (useExistingVpc && vpcId) {
      requestData.vpc_config = {
        vpc_id: vpcId,
        subnet_ids: subnetIds ? subnetIds.split(',').map(s => s.trim()) : undefined,
        security_group_ids: securityGroupIds ? securityGroupIds.split(',').map(s => s.trim()) : undefined,
      };
    }

    try {
      const response = await createCluster(requestData);
      if (response.response?.statusCode === 200) {
        setNotificationItems((items: any) => [
          ...items,
          {
            type: 'success',
            content: `${t('cluster_create_success')}: "${clusterName}"`,
            dismissible: true,
            id: 'create-success',
          },
        ]);
        navigate('/clusters');
      } else {
        throw new Error(response.response?.body || 'Unknown error');
      }
    } catch (error) {
      setNotificationItems((items: any) => [
        ...items,
        {
          type: 'error',
          content: `${t('cluster_create_failed')}: ${error}`,
          dismissible: true,
          id: 'create-error',
        },
      ]);
    } finally {
      setSubmitting(false);
    }
  };

  const handleInstanceGroupChange = (index: number, field: string, value: any) => {
    const updated = [...instanceGroups];
    (updated[index] as any)[field] = value;
    setInstanceGroups(updated);
  };

  const addInstanceGroup = () => {
    setInstanceGroups([
      ...instanceGroups,
      {
        name: `worker-group-${instanceGroups.length + 1}`,
        instance_type: 'ml.g5.4xlarge',
        instance_count: 0,
        min_instance_count: 0,
        use_spot: false,
        training_plan_arn: '',
        storage_volume_size: 500,
        enable_instance_stress_check: false,
        enable_instance_connectivity_check: false,
      },
    ]);
  };

  const removeInstanceGroup = (index: number) => {
    setInstanceGroups(instanceGroups.filter((_, i) => i !== index));
  };

  return (
    <Form
      actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => navigate('/clusters')}>
            {t('cancel')}
          </Button>
          <Button variant="primary" onClick={handleSubmit} loading={submitting}>
            {t('create_cluster')}
          </Button>
        </SpaceBetween>
      }
      header={<Header variant="h1">{t('create_cluster')}</Header>}
    >
      <SpaceBetween size="l">
        {/* Basic Settings */}
        <Container header={<Header variant="h2">{t('basic_settings')}</Header>}>
          <SpaceBetween size="l">
            <FormField label={t('cluster_name')} description={t('cluster_name_desc')}>
              <Input
                value={clusterName}
                onChange={({ detail }) => setClusterName(detail.value)}
                placeholder="my-hyperpod-cluster"
              />
            </FormField>
            <FormField
              label={t('eks_cluster_name')}
              description={t('eks_cluster_name_desc')}
            >
              <Input
                value={eksClusterName}
                onChange={({ detail }) => setEksClusterName(detail.value)}
                placeholder="my-eks-cluster"
              />
            </FormField>
            <FormField label={t('kubernetes_version')}>
              <Select
                selectedOption={kubernetesVersion}
                onChange={({ detail }) => setKubernetesVersion(detail.selectedOption as any)}
                options={kubernetesVersionOptions}
              />
            </FormField>
          </SpaceBetween>
        </Container>

        {/* Instance Groups */}
        <Container
          header={
            <Header
              variant="h2"
              actions={
                <Button onClick={addInstanceGroup} iconName="add-plus">
                  {t('add_instance_group')}
                </Button>
              }
            >
              {t('instance_groups')}
            </Header>
          }
        >
          <SpaceBetween size="l">
            {instanceGroups.map((ig, index) => (
              <Container
                key={index}
                header={
                  <Header
                    variant="h3"
                    actions={
                      instanceGroups.length > 1 && (
                        <Button onClick={() => removeInstanceGroup(index)} iconName="remove">
                          {t('remove')}
                        </Button>
                      )
                    }
                  >
                    {t('instance_group')} {index + 1}
                  </Header>
                }
              >
                <SpaceBetween size="m">
                  <FormField label={t('group_name')}>
                    <Input
                      value={ig.name}
                      onChange={({ detail }) => handleInstanceGroupChange(index, 'name', detail.value)}
                    />
                  </FormField>
                  <FormField label={t('instance_type')}>
                    <Select
                      selectedOption={instanceTypeOptions.find(opt => opt.value === ig.instance_type) || null}
                      onChange={({ detail }) =>
                        handleInstanceGroupChange(index, 'instance_type', detail.selectedOption?.value)
                      }
                      options={instanceTypeOptions}
                    />
                  </FormField>
                  <SpaceBetween direction="horizontal" size="l">
                    <FormField label={t('instance_count')} description={t('instance_count_desc')}>
                      <Input
                        type="number"
                        value={String(ig.instance_count)}
                        onChange={({ detail }) =>
                          handleInstanceGroupChange(index, 'instance_count', parseInt(detail.value) || 0)
                        }
                      />
                    </FormField>
                    <FormField label={t('min_instance_count')} description={t('min_instance_count_desc')}>
                      <Input
                        type="number"
                        value={String(ig.min_instance_count ?? 0)}
                        onChange={({ detail }) =>
                          handleInstanceGroupChange(index, 'min_instance_count', parseInt(detail.value) || 0)
                        }
                      />
                    </FormField>
                  </SpaceBetween>
                  <FormField
                    label={t('storage_volume_size')}
                    description={t('storage_volume_size_desc')}
                  >
                    <Input
                      type="number"
                      value={String(ig.storage_volume_size || 500)}
                      onChange={({ detail }) =>
                        handleInstanceGroupChange(index, 'storage_volume_size', parseInt(detail.value) || 500)
                      }
                      placeholder="500"
                    />
                  </FormField>
                  <FormField
                    label={t('training_plan_arn')}
                    description={t('training_plan_arn_desc')}
                  >
                    <Input
                      value={ig.training_plan_arn || ''}
                      onChange={({ detail }) => handleInstanceGroupChange(index, 'training_plan_arn', detail.value)}
                      placeholder="arn:aws:sagemaker:region:account:training-plan/plan-id"
                    />
                  </FormField>
                  <Checkbox
                    checked={ig.use_spot}
                    onChange={({ detail }) => handleInstanceGroupChange(index, 'use_spot', detail.checked)}
                  >
                    {t('use_spot_instances')}
                  </Checkbox>
                  {ig.use_spot && (
                    <SpotPriceInfo
                      instanceType={ig.instance_type}
                      useSpot={ig.use_spot}
                    />
                  )}
                  <Checkbox
                    checked={ig.enable_instance_stress_check || false}
                    onChange={({ detail }) => handleInstanceGroupChange(index, 'enable_instance_stress_check', detail.checked)}
                  >
                    {t('enable_stress_check')}
                  </Checkbox>
                  <Checkbox
                    checked={ig.enable_instance_connectivity_check || false}
                    onChange={({ detail }) => handleInstanceGroupChange(index, 'enable_instance_connectivity_check', detail.checked)}
                  >
                    {t('enable_connectivity_check')}
                  </Checkbox>
                </SpaceBetween>
              </Container>
            ))}
          </SpaceBetween>
        </Container>

        {/* VPC Settings */}
        <Container header={<Header variant="h2">{t('vpc_settings')}</Header>}>
          <SpaceBetween size="l">
            <Tiles
              value={useExistingVpc ? 'existing' : 'new'}
              onChange={({ detail }) => setUseExistingVpc(detail.value === 'existing')}
              items={[
                { value: 'new', label: t('create_new_vpc'), description: t('create_new_vpc_desc') },
                { value: 'existing', label: t('use_existing_vpc'), description: t('use_existing_vpc_desc') },
              ]}
            />
            {useExistingVpc && (
              <SpaceBetween size="m">
                <FormField label={t('vpc_id')}>
                  <Input
                    value={vpcId}
                    onChange={({ detail }) => setVpcId(detail.value)}
                    placeholder="vpc-xxxxxxxx"
                  />
                </FormField>
                <FormField label={t('subnet_ids')} description={t('subnet_ids_desc')}>
                  <Input
                    value={subnetIds}
                    onChange={({ detail }) => setSubnetIds(detail.value)}
                    placeholder="subnet-xxx, subnet-yyy"
                  />
                </FormField>
                <FormField label={t('sg_ids')} description={t('sg_ids_desc')}>
                  <Input
                    value={securityGroupIds}
                    onChange={({ detail }) => setSecurityGroupIds(detail.value)}
                    placeholder="sg-xxx, sg-yyy"
                  />
                </FormField>
              </SpaceBetween>
            )}
          </SpaceBetween>
        </Container>

        {/* Advanced Settings */}
        <ExpandableSection headerText={t('advanced_settings')} variant="container">
          <SpaceBetween size="l">
            <FormField label={t('node_recovery')}>
              <Tiles
                value={nodeRecovery}
                onChange={({ detail }) => setNodeRecovery(detail.value)}
                items={[
                  { value: 'Automatic', label: t('automatic'), description: t('automatic_desc') },
                  { value: 'None', label: t('none'), description: t('none_recovery_desc') },
                ]}
              />
            </FormField>
            <FormField
              description={t('karpenter_desc')}
            >
              <Checkbox
                checked={enableAutoscaling}
                onChange={({ detail }) => setEnableAutoscaling(detail.checked)}
              >
                {t('enable_karpenter')}
              </Checkbox>
            </FormField>
            <FormField
              label={t('lifecycle_script_s3')}
              description={t('lifecycle_script_s3_desc')}
            >
              <Input
                value={lifecycleScriptS3Uri}
                onChange={({ detail }) => setLifecycleScriptS3Uri(detail.value)}
                placeholder="Leave empty to use default location"
              />
            </FormField>
            <FormField
              label={t('s3_mountpoint_bucket')}
              description={t('s3_mountpoint_bucket_desc')}
            >
              <Input
                value={s3MountBucket}
                onChange={({ detail }) => setS3MountBucket(detail.value)}
                placeholder="my-bucket-name (leave empty for SageMaker default bucket)"
              />
            </FormField>
          </SpaceBetween>
        </ExpandableSection>
      </SpaceBetween>
    </Form>
  );
}

function CreateClusterApp() {
  const appLayout = useRef<any>();
  const { notificationitems } = useSimpleNotifications();

  return (
    <div>
      <TopNav />
      <CustomAppLayout
        ref={appLayout}
        navigation={<Navigation activeHref="/clusters" />}
        notifications={<Flashbar items={notificationitems} stackItems />}
        breadcrumbs={<Breadcrumbs items={clusterBreadcrumbs} />}
        content={<CreateClusterContent />}
        contentType="form"
      />
    </div>
  );
}

export default CreateClusterApp;
