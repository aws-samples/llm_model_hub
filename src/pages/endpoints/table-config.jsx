// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import {
  CollectionPreferences,
  StatusIndicator,
  Link,
  Select,
  Input,
  Autosuggest,
  ButtonDropdown,
} from '@cloudscape-design/components';
import { createTableSortLabelFn } from '../../i18n-strings';
import {formatDateTime} from '../../common/utils';

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
    minWidth: 40,
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


// export const EDITABLE_COLUMN_DEFINITIONS = COLUMN_DEFINITIONS.map(column => {
//   if (editableColumns[column.id]) {
//     return {
//       ...column,
//       minWidth: Math.max(column.minWidth || 0, 176),
//       ...editableColumns[column.id],
//     };
//   }
//   return column;
// });

const CONTENT_DISPLAY_OPTIONS = [
  { id: 'id', label: 'ID', alwaysVisible: true },
  { id: 'status', label: 'Status' },
  { id: 'endpoint_name', label: 'Endpoint name' },
  { id: 'engine', label: 'Engine' },
  { id: 'model_name', label: 'Model' },
  { id: 'instance_type', label: 'Instance type' },
  { id: 'create_time', label: 'Create Time' },
  { id: 'end_time', label: 'End Time' },
  { id: 'enable_lora', label: 'Enable Lora' },
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
    { id: 'model_name', visible: true },
    { id: 'engine', visible: true },
    { id: 'instance_type', visible: true },
    { id: 'create_time', visible: true },
    { id: 'end_time', visible: false },
    { id: 'enable_lora', visible: false },
    { id: 'model_s3_path', visible: true }
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
