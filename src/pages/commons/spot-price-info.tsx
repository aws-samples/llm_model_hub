// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState } from 'react';
import {
  Box,
  StatusIndicator,
  Spinner,
  SpaceBetween,
  ExpandableSection,
  ColumnLayout,
} from '@cloudscape-design/components';
import { remotePost } from '../../common/api-gateway';
import { useTranslation } from 'react-i18next';

interface SpotPriceInfoProps {
  instanceType: string;
  useSpot: boolean;
}

interface PriceData {
  available: boolean;
  min_price?: number;
  max_price?: number;
  price_volatility?: number;
  recommended_az?: string;
  availability_zones?: Array<{
    current_price?: number;
  }>;
}

interface RiskData {
  risk_level?: string;
  risk_description?: string;
}

const SpotPriceInfo: React.FC<SpotPriceInfoProps> = ({ instanceType, useSpot }) => {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [priceData, setPriceData] = useState<PriceData | null>(null);
  const [riskData, setRiskData] = useState<RiskData | null>(null);

  useEffect(() => {
    // Only fetch if we have an instance type and spot is enabled
    if (!instanceType || !useSpot) {
      setPriceData(null);
      setRiskData(null);
      return;
    }

    const fetchSpotInfo = async () => {
      setLoading(true);
      setError(null);

      try {
        // Fetch spot price history
        const priceResponse = await remotePost(
          { instance_types: [instanceType], days: 7 },
          'spot_price_history'
        );

        if (priceResponse?.response?.instance_types?.[instanceType]) {
          setPriceData(priceResponse.response.instance_types[instanceType]);
        } else {
          setPriceData(null);
        }

        // Fetch interruption rate
        const riskResponse = await remotePost(
          { instance_type: instanceType },
          'spot_interruption_rate'
        );

        if (riskResponse?.response) {
          setRiskData(riskResponse.response);
        } else {
          setRiskData(null);
        }
      } catch (err: any) {
        console.error('Error fetching spot price info:', err);
        setError(err.message || 'Failed to fetch spot price info');
      } finally {
        setLoading(false);
      }
    };

    fetchSpotInfo();
  }, [instanceType, useSpot]);

  // Don't show anything if spot is not enabled
  if (!useSpot) {
    return null;
  }

  if (!instanceType) {
    return (
      <Box color="text-status-inactive" padding={{ top: 's' }}>
        <StatusIndicator type="info">{t('spot_select_instance')}</StatusIndicator>
      </Box>
    );
  }

  if (loading) {
    return (
      <Box padding={{ top: 's' }}>
        <SpaceBetween direction="horizontal" size="xs">
          <Spinner size="normal" />
          <span>{t('spot_price_loading')}</span>
        </SpaceBetween>
      </Box>
    );
  }

  if (error) {
    return (
      <Box padding={{ top: 's' }}>
        <StatusIndicator type="error">{t('spot_price_error')}</StatusIndicator>
      </Box>
    );
  }

  if (!priceData?.available) {
    return (
      <Box padding={{ top: 's' }}>
        <StatusIndicator type="warning">{t('spot_not_available')}</StatusIndicator>
      </Box>
    );
  }

  const getRiskStatusType = (riskLevel?: string): 'success' | 'warning' | 'error' | 'info' => {
    switch (riskLevel) {
      case 'low':
        return 'success';
      case 'medium':
        return 'warning';
      case 'high':
        return 'error';
      default:
        return 'info';
    }
  };

  const getRiskLabel = (riskLevel?: string): string => {
    switch (riskLevel) {
      case 'low':
        return t('spot_risk_low');
      case 'medium':
        return t('spot_risk_medium');
      case 'high':
        return t('spot_risk_high');
      default:
        return t('spot_risk_unknown');
    }
  };

  return (
    <Box padding={{ top: 's' }}>
      <ExpandableSection headerText={t('spot_price_info')} variant="footer" defaultExpanded>
        <SpaceBetween size="s">
          <ColumnLayout columns={2} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">{t('spot_current_price')}</Box>
              <Box variant="p">
                ${priceData.availability_zones?.[0]?.current_price?.toFixed(4) || 'N/A'}/hr
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">{t('spot_price_range')}</Box>
              <Box variant="p">
                ${priceData.min_price?.toFixed(4)} - ${priceData.max_price?.toFixed(4)}/hr
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">{t('spot_volatility')}</Box>
              <Box variant="p">{priceData.price_volatility?.toFixed(1)}%</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">{t('spot_risk_level')}</Box>
              <StatusIndicator type={getRiskStatusType(riskData?.risk_level)}>
                {getRiskLabel(riskData?.risk_level)}
              </StatusIndicator>
            </div>
            <div>
              <Box variant="awsui-key-label">{t('spot_recommended_az')}</Box>
              <Box variant="p">{priceData.recommended_az || 'N/A'}</Box>
            </div>
          </ColumnLayout>
          {riskData?.risk_description && (
            <Box variant="small" color="text-body-secondary">
              {riskData.risk_description}
            </Box>
          )}
        </SpaceBetween>
      </ExpandableSection>
    </Box>
  );
};

export default SpotPriceInfo;
