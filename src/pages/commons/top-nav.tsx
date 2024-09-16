// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useState } from 'react';
import { TopNavigation, ButtonDropdownProps } from '@cloudscape-design/components';

import '../../styles/base.scss';
import '../../styles/top-navigation.scss';
import {useAuthUserInfo} from './use-auth';

import logo from '../../resources/model-hub-high-resolution-logo-transparent.webp';
import { useTranslation, Trans } from 'react-i18next';
import i18n from '../../common/i18n';
import ModelSettings from './chat-settings';
 
const i18nStrings = {
  searchIconAriaLabel: 'Search',
  searchDismissIconAriaLabel: 'Close search',
  overflowMenuTriggerText: 'More',
  overflowMenuTitleText: 'All',
  overflowMenuBackIconAriaLabel: 'Back',
  overflowMenuDismissIconAriaLabel: 'Close menu',
};

const profileActions = [
  { id: 'profile', text: 'Profile' },
  { id: 'preferences', text: 'Preferences' },
  { id: 'security', text: 'Security' },
  { id: 'signout', text: 'Sign out' }
];



export const TopNav = () => {

  const userInfo = useAuthUserInfo();
  const {t,i18n} = useTranslation();


  const [modelSettingVisible, setModelSettingVisible] = useState(false);

  return (
    <div>
    <ModelSettings href='' modelSettingVisible={modelSettingVisible} setModelSettingVisible={setModelSettingVisible}/>
    <TopNavigation
      i18nStrings={i18nStrings}
      identity={{
        href: '#',
        // title: 'Model Hub',
        logo: { src: logo, alt: 'Service name logo' },
      }}
      utilities={[
        {
          type: 'button',
          iconName: 'notification',
          ariaLabel: 'Notifications',
          badge: true,
          disableUtilityCollapse: true,
        },
        {
          type: "menu-dropdown",
          iconName: "settings",
          ariaLabel: "Settings",
          title: i18n.t('lang_settings'),
          onItemClick: ({ detail }) => {
            i18n.changeLanguage(detail.id);
            window.location.reload();
          },
          items: [
            {
              id: "en",
              text: "English"
            },
            {
              id: "zh",
              text: "简体中文"
            }
          ]
        },
        {
          type: 'menu-dropdown',
          text: userInfo.username+"@"+userInfo.groupname,
          iconName: 'user-profile',
          onItemClick:({detail}) =>{
            if (detail.id === 'profile'){
              setModelSettingVisible(true)
            }
          },
          items: [{ id: 'profile', text: 'Profile' },
            { id: "signout", text: t('signout'),href: "/signout"}
          ],
        },
      ]}
    />
    </div>
    )
}