import { useEffect, useState, type RefObject } from 'react'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { Button, Col, Input, InputNumber, Row, Select, type InputRef } from 'antd'
import { APPLICATION_STATUSES } from '../../constants/status'
import {
  COMPANY_TYPES,
  INDUSTRIES,
  INTERVIEW_FORMATS,
  INTERVIEW_LANGUAGES,
  INTERVIEW_TYPES,
  JOB_TYPES,
  type ApplicationFilters,
} from '../../types/application'

interface SearchFilterBarProps {
  keyword: string
  filters: ApplicationFilters
  cities: string[]
  onKeywordChange: (value: string) => void
  onFilterChange: (filters: ApplicationFilters) => void
  onReset: () => void
  searchInputRef?: RefObject<InputRef | null>
}

export function SearchFilterBar({
  keyword,
  filters,
  cities,
  onKeywordChange,
  onFilterChange,
  onReset,
  searchInputRef,
}: SearchFilterBarProps) {
  const [inputValue, setInputValue] = useState(keyword)

  useEffect(() => {
    setInputValue(keyword)
  }, [keyword])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (inputValue !== keyword) {
        onKeywordChange(inputValue)
      }
    }, 300)

    return () => window.clearTimeout(timer)
  }, [inputValue, keyword, onKeywordChange])

  return (
    <Row gutter={[12, 12]}>
      <Col xs={24} md={8}>
        <Input
          ref={searchInputRef}
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索公司、岗位、城市、行业"
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
        />
      </Col>
      <Col xs={12} md={4}>
        <Select
          allowClear
          placeholder="公司类型"
          options={COMPANY_TYPES.map((item) => ({ label: item, value: item }))}
          value={filters.companyType}
          onChange={(value) => onFilterChange({ ...filters, companyType: value })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={12} md={4}>
        <Select
          allowClear
          placeholder="城市"
          options={cities.map((item) => ({ label: item, value: item }))}
          value={filters.city}
          onChange={(value) => onFilterChange({ ...filters, city: value })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={12} md={4}>
        <Select
          allowClear
          placeholder="招聘类型"
          options={JOB_TYPES.map((item) => ({ label: item, value: item }))}
          value={filters.jobType}
          onChange={(value) => onFilterChange({ ...filters, jobType: value })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={12} md={4}>
        <Select
          allowClear
          placeholder="状态"
          options={APPLICATION_STATUSES.map((item) => ({ label: item, value: item }))}
          value={filters.status}
          onChange={(value) => onFilterChange({ ...filters, status: value })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={12} md={4}>
        <Select
          allowClear
          placeholder="行业"
          options={INDUSTRIES.map((item) => ({ label: item, value: item }))}
          value={filters.industry}
          onChange={(value) => onFilterChange({ ...filters, industry: value })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={12} md={4}>
        <Select
          allowClear
          placeholder="面试语言"
          options={INTERVIEW_LANGUAGES.map((item) => ({ label: item, value: item }))}
          value={filters.interviewLanguage}
          onChange={(value) => onFilterChange({ ...filters, interviewLanguage: value })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={12} md={4}>
        <Select
          allowClear
          placeholder="面试形式"
          options={INTERVIEW_FORMATS.map((item) => ({ label: item, value: item }))}
          value={filters.interviewFormat}
          onChange={(value) => onFilterChange({ ...filters, interviewFormat: value })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={12} md={4}>
        <Select
          allowClear
          placeholder="面试类型"
          options={INTERVIEW_TYPES.map((item) => ({ label: item, value: item }))}
          value={filters.interviewType}
          onChange={(value) => onFilterChange({ ...filters, interviewType: value })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={12} md={4}>
        <Select
          allowClear
          placeholder="是否 Offer"
          options={[
            { label: '已收到 Offer', value: true },
            { label: '未收到 Offer', value: false },
          ]}
          value={filters.offerReceived}
          onChange={(value) => onFilterChange({ ...filters, offerReceived: value })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={12} md={4}>
        <Select
          allowClear
          placeholder="可转正"
          options={[
            { label: '可转正', value: true },
            { label: '不可转正', value: false },
          ]}
          value={filters.canConvert}
          onChange={(value) => onFilterChange({ ...filters, canConvert: value })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={12} md={3}>
        <InputNumber
          min={0}
          placeholder="最低金额"
          value={filters.salaryMin}
          onChange={(value) => onFilterChange({ ...filters, salaryMin: value ?? undefined })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={12} md={3}>
        <InputNumber
          min={0}
          placeholder="最高金额"
          value={filters.salaryMax}
          onChange={(value) => onFilterChange({ ...filters, salaryMax: value ?? undefined })}
          style={{ width: '100%' }}
        />
      </Col>
      <Col xs={24} md={4}>
        <Button block icon={<ReloadOutlined />} onClick={onReset}>
          清空筛选
        </Button>
      </Col>
    </Row>
  )
}
