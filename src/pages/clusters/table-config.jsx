// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import { CollectionPreferences, StatusIndicator, Link } from '@cloudscape-design/components';

const statusTypeMap = {
  PENDING: 'pending',
  CREATING: 'in-progress',
  UPDATING: 'in-progress',
  ACTIVE: 'success',
  DELETING: 'in-progress',
  FAILED: 'error',
  DELETED: 'stopped',
};

const statusLabelMap = {
  PENDING: 'Pending',
  CREATING: 'Creating',
  UPDATING: 'Updating',
  ACTIVE: 'Active',
  DELETING: 'Deleting',
  FAILED: 'Failed',
  DELETED: 'Deleted',
};

export const COLUMN_DEFINITIONS = [
  {
    id: 'cluster_name',
    sortingField: 'cluster_name',
    header: 'Cluster Name',
    cell: item => (
      <Link href={`/clusters/${item.cluster_id}`}>{item.cluster_name}</Link>
    ),
    width: 200,
  },
  {
    id: 'eks_cluster_name',
    sortingField: 'eks_cluster_name',
    header: 'EKS Cluster',
    cell: item => item.eks_cluster_name || '-',
    width: 180,
  },
  {
    id: 'cluster_status',
    sortingField: 'cluster_status',
    header: 'Status',
    cell: item => (
      <StatusIndicator type={statusTypeMap[item.cluster_status] || 'pending'}>
        {statusLabelMap[item.cluster_status] || item.cluster_status}
      </StatusIndicator>
    ),
    width: 120,
  },
  {
    id: 'instance_groups',
    header: 'Instance Groups',
    cell: item => {
      if (!item.instance_groups || item.instance_groups.length === 0) {
        return '-';
      }
      return item.instance_groups.map(ig => `${ig.name}(${ig.instance_count})`).join(', ');
    },
    width: 200,
  },
  {
    id: 'vpc_id',
    header: 'VPC ID',
    cell: item => item.vpc_id || '-',
    width: 150,
  },
  {
    id: 'cluster_create_time',
    sortingField: 'cluster_create_time',
    header: 'Created',
    cell: item => item.cluster_create_time || '-',
    width: 180,
  },
  {
    id: 'error_message',
    header: 'Error',
    cell: item => item.error_message ? (
      <span title={item.error_message}>
        {item.error_message.substring(0, 50)}...
      </span>
    ) : '-',
    width: 200,
  },
];

export const DEFAULT_PREFERENCES = {
  pageSize: 20,
  contentDisplay: [
    { id: 'cluster_name', visible: true },
    { id: 'eks_cluster_name', visible: true },
    { id: 'cluster_status', visible: true },
    { id: 'instance_groups', visible: true },
    { id: 'vpc_id', visible: true },
    { id: 'cluster_create_time', visible: true },
    { id: 'error_message', visible: false },
  ],
  wrapLines: false,
  stripedRows: false,
  contentDensity: 'comfortable',
  stickyColumns: { first: 1, last: 0 },
};

export const PAGE_SIZE_OPTIONS = [
  { value: 10, label: '10 items' },
  { value: 20, label: '20 items' },
  { value: 50, label: '50 items' },
];

export const CONTENT_DISPLAY_OPTIONS = [
  { id: 'cluster_name', label: 'Cluster Name', alwaysVisible: true },
  { id: 'eks_cluster_name', label: 'EKS Cluster' },
  { id: 'cluster_status', label: 'Status' },
  { id: 'instance_groups', label: 'Instance Groups' },
  { id: 'vpc_id', label: 'VPC ID' },
  { id: 'cluster_create_time', label: 'Created' },
  { id: 'error_message', label: 'Error' },
];

export function Preferences({ preferences, setPreferences, disabled }) {
  return (
    <CollectionPreferences
      title="Preferences"
      confirmLabel="Confirm"
      cancelLabel="Cancel"
      disabled={disabled}
      preferences={preferences}
      onConfirm={({ detail }) => setPreferences(detail)}
      pageSizePreference={{
        title: 'Page size',
        options: PAGE_SIZE_OPTIONS,
      }}
      wrapLinesPreference={{
        label: 'Wrap lines',
        description: 'Select to see all the text and wrap the lines',
      }}
      stripedRowsPreference={{
        label: 'Striped rows',
        description: 'Select to add alternating shaded rows',
      }}
      contentDensityPreference={{
        label: 'Compact mode',
        description: 'Select to display content in a denser, more compact mode',
      }}
      contentDisplayPreference={{
        title: 'Column preferences',
        description: 'Select columns to display',
        options: CONTENT_DISPLAY_OPTIONS,
      }}
      stickyColumnsPreference={{
        firstColumns: {
          title: 'Stick first column(s)',
          description: 'Keep the first column(s) visible while horizontally scrolling',
          options: [
            { label: 'None', value: 0 },
            { label: 'First column', value: 1 },
            { label: 'First two columns', value: 2 },
          ],
        },
        lastColumns: {
          title: 'Stick last column',
          description: 'Keep the last column visible while horizontally scrolling',
          options: [
            { label: 'None', value: 0 },
            { label: 'Last column', value: 1 },
          ],
        },
      }}
    />
  );
}
