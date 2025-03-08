// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import {
  CollectionPreferences,
  StatusIndicator,
  Link
} from '@cloudscape-design/components';
import { createTableSortLabelFn } from '../../i18n-strings';

const rawColumns = [
  {
    id: 'id',
    sortingField: 'id',
    header: 'ID',
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
    id: 'inference_component_name',
    sortingField: 'inference_component_name',
    cell: item => JSON.parse(item.extra_config)?.inference_component_name,
    header: 'Inference Component Name',
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
    header: 'Initial Instance count',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'current_instance_count',
    sortingField: 'current_instance_count',
    cell: item => JSON.parse(item.extra_config)?.endpoint_instance_count?.current_instance_count,
    header: 'Current Instance count',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'desired_instance_count',
    sortingField: 'desired_instance_count',
    cell: item => JSON.parse(item.extra_config)?.endpoint_instance_count?.desired_instance_count,
    header: 'Desired Instance count',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'max_instance_count',
    sortingField: 'max_instance_count',
    cell: item => JSON.parse(item.extra_config)?.max_instance_count,
    header: 'Max Instance count',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'min_instance_count',
    sortingField: 'min_instance_count',
    cell: item => JSON.parse(item.extra_config)?.min_instance_count,
    header: 'Min Instance count',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'target_tps',
    sortingField: 'target_tps',
    cell: item => JSON.parse(item.extra_config)?.target_tps,
    header: 'Target TPS',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'in_cooldown',
    sortingField: 'in_cooldown',
    cell: item => JSON.parse(item.extra_config)?.in_cooldown,
    header: 'Scale-In Cooldown',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'out_cooldown',
    sortingField: 'out_cooldown',
    cell: item => JSON.parse(item.extra_config)?.out_cooldown,
    header: 'Scale-Out Cooldown',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'target_tps',
    sortingField: 'target_tps',
    cell: item => JSON.parse(item.extra_config)?.target_tps,
    header: 'Target TPS',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'min_copy_count',
    sortingField: 'min_copy_count',
    cell: item => JSON.parse(item.extra_config)?.inference_component_copies?.min_copy_count,
    header: 'Min IC Copy count',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'max_copy_count',
    sortingField: 'max_copy_count',
    cell: item => JSON.parse(item.extra_config)?.inference_component_copies?.max_copy_count,
    header: 'Max IC Copy count',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'current_copy_count',
    sortingField: 'current_copy_count',
    cell: item => JSON.parse(item.extra_config)?.inference_component_copies?.current_copy_count,
    header: 'Current IC Copy count',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'desired_copy_count',
    sortingField: 'desired_copy_count',
    cell: item => JSON.parse(item.extra_config)?.inference_component_copies?.desired_copy_count,
    header: 'Desired IC Copy count',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'status',
    sortingField: 'status',
    header: 'Endpoint Status',
    cell: item => (
      <StatusIndicator type={item.endpoint_status === 'INSERVICE' ? 'success' : 
        item.endpoint_status === 'ERROR' ? "error" : 
        item.endpoint_status === 'TERMINATED' ? "stopped" : 
        item.endpoint_status === 'FAILED' ? "error": "loading"
      }>{item.endpoint_status}</StatusIndicator>
    ),
    minWidth: 40,
  },
  {
    id: 'inference_status',
    sortingField: 'inference_status',
    header: 'Inference Component Status',
    cell: item => (
      <StatusIndicator  type={JSON.parse(item.extra_config)?.inference_component_status === 'INSERVICE' ? 'success' : 
        JSON.parse(item.extra_config)?.inference_component_status === 'TERMINATED' ? "stopped" : 
        JSON.parse(item.extra_config)?.inference_component_status === 'FAILED' ? "error": "loading"
      }>{JSON.parse(item.extra_config)?.inference_component_status}</StatusIndicator>
    ),
    minWidth: 40,
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
    id: 'model_s3_path',
    sortingField: 'model_s3_path',
    cell: item => item.model_s3_path,
    header: 'Model file Path',
    minWidth: 160,
    isRowHeader: true,
  },
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
  { id: 'id', label: 'ID', alwaysVisible: true },
  { id: 'status', label: 'Endpoint Status' },
  { id: 'inference_status', label: 'Inference Component Status' },
  { id: 'endpoint_name', label: 'Endpoint name' },
  { id: 'inference_component_name', label: 'Inference Componet Name'},
  { id: 'model_name', label: 'Model' },
  { id: 'engine', label: 'Engine' },
  { id: 'instance_type', label: 'Instance type'},
  { id: 'instance_count', label: 'Initial Instance count' },
  { id: 'min_instance_count', label: 'Min Instance count' },
  { id: 'max_instance_count', label: 'Max Instance count' },
  { id: 'current_instance_count', label: 'Current Instance count'},
  { id: 'desired_instance_count', label: 'Desired Instance count' },
  { id: 'min_copy_count', label: 'Min IC Copy count' },
  { id: 'max_copy_count', label: 'Max IC Copy count' },
  { id: 'current_copy_count', label: 'Current IC Copy Count' } ,
  { id: 'current_copy_count', label: 'Current IC Copy Count' } ,
  { id: 'desired_copy_count', label: 'Desired IC Copy count' },
  { id: 'target_tps', label: 'Target TPS' } ,
  { id: 'in_cooldown', label: 'Scale-In Cooldown' } ,
  { id: 'out_cooldown', label: 'Scale-Out Cooldown' } ,
  { id: 'create_time', label: 'Create Time' },
  { id: 'model_s3_path', label: 'Model S3 Path'}
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
    { id: 'inference_status', visible: true },
    { id: 'endpoint_name', visible: true },
    { id: 'inference_component_name', visible: false },
    { id: 'model_name', visible: true },
    { id: 'engine', visible: true },
    { id: 'instance_type', visible: true },
    { id: 'instance_count', visible: true },
    { id: 'min_instance_count', visible: true},
    { id: 'max_instance_count', visible: true},
    { id: 'current_instance_count', visible: true},
    { id: 'desired_instance_count', visible: false},
    { id: 'current_copy_count', visible: true},
    { id: 'desired_copy_count', visible: false},
    { id: 'create_time', visible: true },
    { id: 'model_s3_path', visible: false }
  ],
  wrapLines: false,
  stripedRows: true,
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
