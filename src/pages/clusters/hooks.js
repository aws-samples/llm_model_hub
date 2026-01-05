// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState } from 'react';
import { remotePost } from '../../common/api-gateway';

export function useClusters(params = {}) {
  const { pageSize, currentPageIndex: clientPageIndex } = params.pagination || {};
  const { sortingDescending, sortingColumn } = params.sorting || {};
  const { filteringText, filteringTokens, filteringOperation } = params.filtering || {};
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [currentPageIndex, setCurrentPageIndex] = useState(clientPageIndex);
  const [pagesCount, setPagesCount] = useState(0);

  useEffect(() => {
    setCurrentPageIndex(clientPageIndex);
  }, [clientPageIndex]);

  useEffect(() => {
    setLoading(true);
    const controller = new AbortController();
    const requestParams = {
      "page_size": pageSize,
      "page_index": currentPageIndex
    };

    remotePost(requestParams, 'list_clusters').then((res) => {
      setLoading(false);
      setItems(res.clusters || []);
      setPagesCount(Math.ceil(res.total_count / pageSize));
      setCurrentPageIndex(currentPageIndex);
      setTotalCount(res.total_count);
    }).catch((error) => {
      console.log(error);
      setLoading(false);
      setItems([]);
    });

    return () => {
      controller.abort();
    }
  }, [
    pageSize,
    sortingDescending,
    sortingColumn,
    currentPageIndex,
    filteringText,
    filteringTokens,
    filteringOperation,
    params.refresh
  ]);

  return {
    items,
    loading,
    totalCount,
    pagesCount,
    currentPageIndex,
  };
}

export async function createCluster(clusterData) {
  try {
    const response = await remotePost(clusterData, 'create_cluster');
    return response;
  } catch (error) {
    console.error('Error creating cluster:', error);
    throw error;
  }
}

export async function deleteCluster(clusterId, deleteVpc = false) {
  try {
    const response = await remotePost({
      cluster_id: clusterId,
      delete_vpc: deleteVpc
    }, 'delete_cluster');
    return response;
  } catch (error) {
    console.error('Error deleting cluster:', error);
    throw error;
  }
}

export async function getCluster(clusterId) {
  try {
    const response = await remotePost({
      cluster_id: clusterId
    }, 'get_cluster');
    return response;
  } catch (error) {
    console.error('Error getting cluster:', error);
    throw error;
  }
}

export async function updateClusterInstanceGroups(clusterId, instanceGroups) {
  try {
    const response = await remotePost({
      cluster_id: clusterId,
      instance_groups: instanceGroups
    }, 'update_cluster_instance_groups');
    return response;
  } catch (error) {
    console.error('Error updating instance groups:', error);
    throw error;
  }
}

export async function listClusterNodes(clusterId) {
  try {
    const response = await remotePost({
      cluster_id: clusterId
    }, 'list_cluster_nodes');
    return response;
  } catch (error) {
    console.error('Error listing cluster nodes:', error);
    throw error;
  }
}
