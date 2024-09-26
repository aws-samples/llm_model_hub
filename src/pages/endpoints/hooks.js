// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState } from 'react';
import { remotePost } from '../../common/api-gateway';
export function useDistributions(params = {}) {
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
    const params1 = {
      filteringText,
      filteringTokens,
      filteringOperation,
      pageSize,
      currentPageIndex,
      sortingDescending,
      ...(sortingColumn
        ? {
            sortingColumn: sortingColumn.sortingField,
          }
        : {}),
    };
    const controller = new AbortController();
    const params = {
      "page_size":pageSize,
      "page_index":currentPageIndex
    }
    remotePost(params,'list_endpoints').then((res) => {
      // console.log(res);  
      setLoading(false);
      setItems(res.endpoints);
      setPagesCount(Math.ceil(res.total_count/pageSize));
      setCurrentPageIndex(currentPageIndex);
      setTotalCount(res.total_count);
    }).catch((error) => {
      console.log(error);
      setLoading(false);
      setItems([]);
    });

    return ()=>{
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
