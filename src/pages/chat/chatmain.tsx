// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useRef, useState } from "react";
import { CustomAppLayout, Navigation } from "../commons/common-components";
import { Breadcrumbs, chatBreadcrumbs } from '../commons/breadcrumbs'
import { TopNav } from "../commons/top-nav";
import { useParams } from "react-router-dom";

import Content from "./content";

const ChatBot = () => {
  const appLayout = useRef(null);
  const { endpoint } = useParams();


  return (
    <div>
      <TopNav />
      <CustomAppLayout
        ref={appLayout}
        navigation={<Navigation activeHref="/chat" />}
        breadcrumbs={<Breadcrumbs items={chatBreadcrumbs} />}
        content={
          <Content endpoint={endpoint}/>
        }

        contentType="table"
        stickyNotifications
      />
    </div>
  );
};

export default ChatBot;
