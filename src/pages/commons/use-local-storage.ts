// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
// import { useState } from 'react';
// import { load, save } from '../../common/localStorage';

// export function useLocalStorage<T>(key: string, defaultValue?: T) {
//   const [value, setValue] = useState<T>(() => load(key) ?? defaultValue);

//   function handleValueChange(newValue: T) {
//     setValue(newValue);
//     save(key, newValue);
//   }

//   return [value, handleValueChange] as const;
// }

import { useState } from 'react';

export const save = (key: string, value: any): void => {
  localStorage.setItem(key, JSON.stringify(value));
};

export const load = (key: string): any | undefined => {
  const value = localStorage.getItem(key);
  try {
    return value && JSON.parse(value);
  } catch (e) {
    console.warn(
      `⚠️ The ${key} value that is stored in localStorage is incorrect. Try to remove the value ${key} from localStorage and reload the page`
    );
    return undefined;
  }
};

export const useLocalStorage = <T>(key: string, defaultValue: T): [T, (newValue: T) => void] => {
  const [value, setValue] = useState<T>(() => load(key) ?? defaultValue);

  function handleValueChange(newValue: T): void {
    setValue(newValue);
    save(key, newValue);
  }

  return [value, handleValueChange];
};

