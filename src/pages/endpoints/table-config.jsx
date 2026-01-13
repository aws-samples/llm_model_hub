// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useState } from 'react';
import {
  CollectionPreferences,
  StatusIndicator,
  Link,
  Box,
  Button,
  Popover,
  Badge,
} from '@cloudscape-design/components';
import { createTableSortLabelFn } from '../../i18n-strings';

// Helper function to mask API key for display
const maskApiKey = (apiKey) => {
  if (!apiKey || apiKey.length < 8) return apiKey || '-';
  const visibleStart = 4;
  const visibleEnd = 4;
  return `${apiKey.substring(0, visibleStart)}...${apiKey.substring(apiKey.length - visibleEnd)}`;
};

// Helper function to parse extra_config
const parseExtraConfig = (item) => {
  if (!item.extra_config) return {};
  try {
    return typeof item.extra_config === 'string'
      ? JSON.parse(item.extra_config)
      : item.extra_config;
  } catch {
    return {};
  }
};

// Helper function to get API key from item's extra_config
const getApiKey = (item) => {
  const config = parseExtraConfig(item);
  return config.api_key || null;
};

// Helper function to get network access type (Public/Private) for HyperPod endpoints
const getNetworkAccess = (item) => {
  if (item.deployment_target !== 'hyperpod') return null;
  const config = parseExtraConfig(item);
  return config.use_public_alb ? 'Public' : 'Private';
};

// Helper function to get ALB URL from item's extra_config
const getAlbUrl = (item) => {
  if (item.deployment_target !== 'hyperpod') return null;
  const config = parseExtraConfig(item);
  return config.alb_url || config.endpoint_url || null;
};

// Helper function to get HyperPod cluster name from item's extra_config
const getHyperpodCluster = (item) => {
  if (item.deployment_target !== 'hyperpod') return null;
  const config = parseExtraConfig(item);
  return config.eks_cluster_name || null;
};

// Custom copy function with fallback for non-secure contexts
const copyToClipboard = async (text) => {
  // Try modern Clipboard API first
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.warn('Clipboard API failed:', err);
    }
  }

  // Fallback: use textarea + execCommand
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.style.position = 'fixed';
  textArea.style.left = '-999999px';
  textArea.style.top = '-999999px';
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  try {
    const successful = document.execCommand('copy');
    document.body.removeChild(textArea);
    return successful;
  } catch (err) {
    console.error('Fallback copy failed:', err);
    document.body.removeChild(textArea);
    return false;
  }
};

// ALB URL cell component with copy functionality
const AlbUrlCell = ({ url }) => {
  const [copyStatus, setCopyStatus] = useState(null);

  const handleCopy = async () => {
    const success = await copyToClipboard(url);
    setCopyStatus(success ? 'success' : 'error');
    setTimeout(() => setCopyStatus(null), 2000);
  };

  // Truncate URL for display
  const displayUrl = url.length > 40 ? `${url.substring(0, 40)}...` : url;

  return (
    <Box display="inline-flex" alignItems="center">
      <span style={{ marginRight: '8px', fontFamily: 'monospace', fontSize: '12px' }} title={url}>
        {displayUrl}
      </span>
      <Popover
        dismissButton={false}
        position="top"
        size="small"
        triggerType="custom"
        visible={copyStatus !== null}
        content={
          <StatusIndicator type={copyStatus === 'success' ? 'success' : 'error'}>
            {copyStatus === 'success' ? 'URL copied' : 'Failed to copy'}
          </StatusIndicator>
        }
        renderWithPortal={true}
      >
        <Button
          iconName="copy"
          variant="inline-icon"
          ariaLabel="Copy ALB URL"
          onClick={handleCopy}
        />
      </Popover>
    </Box>
  );
};

// API Key cell component with copy functionality
const ApiKeyCell = ({ apiKey }) => {
  const [copyStatus, setCopyStatus] = useState(null);

  const handleCopy = async () => {
    const success = await copyToClipboard(apiKey);
    setCopyStatus(success ? 'success' : 'error');
    setTimeout(() => setCopyStatus(null), 2000);
  };

  return (
    <Box display="inline-flex" alignItems="center">
      <span style={{ marginRight: '8px', fontFamily: 'monospace' }}>{maskApiKey(apiKey)}</span>
      <Popover
        dismissButton={false}
        position="top"
        size="small"
        triggerType="custom"
        visible={copyStatus !== null}
        content={
          <StatusIndicator type={copyStatus === 'success' ? 'success' : 'error'}>
            {copyStatus === 'success' ? 'API key copied' : 'Failed to copy'}
          </StatusIndicator>
        }
        renderWithPortal={true}
      >
        <Button
          iconName="copy"
          variant="inline-icon"
          ariaLabel="Copy API key"
          onClick={handleCopy}
        />
      </Popover>
    </Box>
  );
};

const rawColumns = [
  {
    id: 'id',
    sortingField: 'id',
    header: 'Training Job ID',
    cell: item => (
      <div>
        <Link href={`/jobs/${item.job_id}`}>{item.job_id}</Link>
      </div>
    ),
    minWidth: 180,
  },
  {
    id: 'endpoint_name',
    sortingField: 'endpoint_name',
    cell: item => item.endpoint_name,
    header: 'Endpoint Name',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'model_name',
    sortingField: 'model_name',
    cell: item => item.model_name,
    header: 'Model',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'deployment_target',
    sortingField: 'deployment_target',
    cell: item => (
      <Badge color={item.deployment_target === 'hyperpod' ? 'blue' : 'green'}>
        {item.deployment_target === 'hyperpod' ? 'HyperPod' : 'SageMaker'}
      </Badge>
    ),
    header: 'Target',
    minWidth: 100,
    isRowHeader: true,
  },
  {
    id: 'hyperpod_cluster',
    header: 'Cluster',
    cell: item => {
      const cluster = getHyperpodCluster(item);
      if (!cluster) return '-';
      return cluster;
    },
    minWidth: 120,
  },
  {
    id: 'network_access',
    header: 'Network',
    cell: item => {
      const access = getNetworkAccess(item);
      if (!access) return '-';
      return (
        <Badge color={access === 'Public' ? 'green' : 'grey'}>
          {access}
        </Badge>
      );
    },
    minWidth: 90,
  },
  {
    id: 'api_key',
    header: 'API Key',
    cell: item => {
      const apiKey = getApiKey(item);
      if (!apiKey) return '-';
      return <ApiKeyCell apiKey={apiKey} />;
    },
    minWidth: 180,
  },
  {
    id: 'alb_url',
    header: 'ALB URL',
    cell: item => {
      const albUrl = getAlbUrl(item);
      if (!albUrl) return '-';
      return <AlbUrlCell url={albUrl} />;
    },
    minWidth: 200,
  },
  {
    id: 'engine',
    sortingField: 'engine',
    cell: item => item.engine,
    header: 'Engine',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'instance_type',
    sortingField: 'instance_type',
    cell: item => item.instance_type,
    header: 'Instance',
    minWidth: 120,
    isRowHeader: true,
  },
  {
    id: 'instance_count',
    sortingField: 'instance_count',
    cell: item => item.instance_count,
    header: 'Instance count',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'status',
    sortingField: 'status',
    header: 'Status',
    cell: item => (
      <StatusIndicator type={item.endpoint_status === 'INSERVICE' ? 'success' : 
        item.endpoint_status === 'ERROR' ? "error" : 
        item.endpoint_status === 'TERMINATED' ? "stopped" : 
        item.endpoint_status === 'FAILED' ? "error": "loading"
      }>{item.endpoint_status}</StatusIndicator>
    ),
    minWidth: 120,
  },
  {
    id: 'create_time',
    sortingField: 'create_time',
    cell: item => item.endpoint_create_time,
    header: 'Create Time',
    minWidth: 120,
    isRowHeader: true,
  },
  {
    id: 'end_time',
    sortingField: 'end_time',
    // cell: item => formatDateTime(item.job_end_time),
    cell: item => item.endpoint_delete_time,
    header: 'End Time',
    minWidth: 120,
    isRowHeader: true,
  },
  {
    id: 'enable_lora',
    sortingField: 'enable_lora',
    cell: item => item.enable_lora,
    header: 'Enable Lora',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'model_s3_path',
    sortingField: 'model_s3_path',
    cell: item => item.model_s3_path,
    header: 'Model file Path',
    minWidth: 160,
    isRowHeader: true,
  },
  // {
  //   id: 'actions',
  //   header: 'Actions',
  //   minWidth: 100,
  //   cell: item => (
  //     <ButtonDropdown
  //       variant="inline-icon"
  //       ariaLabel={`${item.id} actions`}
  //       expandToViewport={true}
  //       items={[
  //         { id: 'view', text: 'View details' },
  //         { id: 'edit', text: 'Edit' },
  //         { id: 'delete', text: 'Delete' },
  //       ]}
  //     />
  //   ),
  // },
];


export const JOB_STATE = {
  PENDING : "PENDING",
  SUBMITTED : "SUBMITTED",
  CREATING : "CREATING",
  RUNNING : "RUNNING",
  SUCCESS : "SUCCESS",
  ERROR : "ERROR",
  TERMINATED : "TERMINATED",
  TERMINATING : "TERMINATING",
  STOPPED : "STOPPED"
}

export const COLUMN_DEFINITIONS = rawColumns.map(column => ({ ...column, ariaLabel: createTableSortLabelFn(column) }));

export const serverSideErrorsStore = new Map();

const CONTENT_DISPLAY_OPTIONS = [
  { id: 'id', label: 'Training Job ID', alwaysVisible: true },
  { id: 'status', label: 'Status' },
  { id: 'endpoint_name', label: 'Endpoint name' },
  { id: 'deployment_target', label: 'Target' },
  { id: 'hyperpod_cluster', label: 'Cluster' },
  { id: 'network_access', label: 'Network' },
  { id: 'api_key', label: 'API Key' },
  { id: 'alb_url', label: 'ALB URL' },
  { id: 'engine', label: 'Engine' },
  { id: 'model_name', label: 'Model' },
  { id: 'instance_type', label: 'Instance type' },
  { id: 'instance_count', label: 'Instance count' },
  { id: 'create_time', label: 'Create Time' },
  { id: 'end_time', label: 'End Time' },
  // { id: 'enable_lora', label: 'Enable Lora' },
  { id: 'model_s3_path', label: 'Model S3 Path' },
  // { id: 'actions', label: 'Actions' },

];

export const PAGE_SIZE_OPTIONS = [
  { value: 10, label: '10 Records' },
  { value: 30, label: '30 Records' },
  { value: 50, label: '50 Records' },
];

export const DEFAULT_PREFERENCES = {
  pageSize: 30,
  contentDisplay: [
    { id: 'id', visible: true },
    { id: 'status', visible: true },
    { id: 'endpoint_name', visible: true },
    { id: 'deployment_target', visible: true },
    { id: 'hyperpod_cluster', visible: true },
    { id: 'network_access', visible: true },
    { id: 'api_key', visible: true },
    { id: 'alb_url', visible: true },
    { id: 'model_name', visible: true },
    { id: 'engine', visible: true },
    { id: 'instance_type', visible: true },
    { id: 'instance_count', visible: true },
    { id: 'create_time', visible: true },
    { id: 'end_time', visible: false },
    { id: 'model_s3_path', visible: false }
  ],
  wrapLines: false,
  stripedRows: false,
  contentDensity: 'comfortable',
  stickyColumns: { first: 0, last: 1 },
};

export const Preferences = ({
  preferences,
  setPreferences,
  disabled,
  pageSizeOptions = PAGE_SIZE_OPTIONS,
  contentDisplayOptions = CONTENT_DISPLAY_OPTIONS,
}) => (
  <CollectionPreferences
    disabled={disabled}
    preferences={preferences}
    onConfirm={({ detail }) => setPreferences(detail)}
    pageSizePreference={{ options: pageSizeOptions }}
    wrapLinesPreference={{}}
    stripedRowsPreference={{}}
    contentDensityPreference={{}}
    contentDisplayPreference={{ options: contentDisplayOptions }}
    stickyColumnsPreference={{
      firstColumns: {
        title: 'Stick first column(s)',
        description: 'Keep the first column(s) visible while horizontally scrolling the table content.',
        options: [
          { label: 'None', value: 0 },
          { label: 'First column', value: 1 },
          { label: 'First two columns', value: 2 },
        ],
      },
      lastColumns: {
        title: 'Stick last column',
        description: 'Keep the last column visible while horizontally scrolling the table content.',
        options: [
          { label: 'None', value: 0 },
          { label: 'Last column', value: 1 },
        ],
      },
    }}
  />
);
